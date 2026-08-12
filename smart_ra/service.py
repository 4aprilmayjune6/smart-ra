"""서비스 계층 — 오케스트레이션. MCP 서버·REST API·CLI가 공유한다(SFR-607).

RFP 표준 처리 흐름(3.3): 등록 → 수집 → 모듈 1·2·3 병렬 → 교차검증(모듈4) → 메모 →
검토·승인 → JET 연동. 승인은 서비스 계층에서 웹 콘솔 역할로만 노출하며 MCP 도구로는
제공하지 않는다(SFR-604).
"""
from __future__ import annotations

from . import RULE_VERSION
from .dart import get_adapter
from .dart.schema import CompanyRecord
from .external.sources import build_external_signals
from .guards import assert_cited, assert_no_injection
from .memo.generator import generate_memo
from .models import (
    CrossValidationResult,
    Engagement,
    GoingConcernAssessment,
    Job,
    JobStatus,
    JobType,
    Memo,
    MemoStatus,
    ParseIssue,
    Severity,
    Signal,
    content_id,
)
from .modules import AnalysisContext
from .modules import module1_disclosure as m1
from .modules import module2_industry as m2
from .modules import module3_going_concern as m3
from .modules import module4_crossval as m4
from .modules.module2_industry import match_profile
from .storage import Repository


class EngagementNotFound(KeyError):
    pass


# 외부 공개정보 신호 카테고리(기사·감리사례) — 재수집 시 별도 재적용 대상
_EXTERNAL_CATEGORIES = ("EXTERNAL_NEWS", "REVIEW_PRECEDENT")


class SmartRaService:
    def __init__(self, repo: Repository | None = None, adapter=None) -> None:
        self.repo = repo or Repository()
        self.adapter = adapter or get_adapter()

    # ── 인게이지먼트 ───────────────────────────────────────────────────────────
    def list_engagements(self) -> list[Engagement]:
        return self.repo.list_engagements()

    def _require(self, engagement_id: str) -> Engagement:
        e = self.repo.get_engagement(engagement_id)
        if e is None:
            raise EngagementNotFound(engagement_id)
        return e

    def register_engagement(self, query: str, fiscal_year: int, team: str | None = None) -> tuple[Engagement, Job]:
        identity = self.adapter.resolve_corp(query)
        if identity is None:
            raise EngagementNotFound(f"회사 식별 실패: {query}")
        engagement_id = content_id("ENG", identity.corp_code, str(fiscal_year))
        engagement = Engagement(
            engagement_id=engagement_id, corp_code=identity.corp_code,
            corp_name=identity.corp_name, stock_code=identity.stock_code,
            ksic_code=identity.ksic_code, fiscal_year=fiscal_year, team=team,
        )
        self.repo.save_engagement(engagement)
        job = self._collect_and_analyze(engagement)
        return self.repo.get_engagement(engagement_id), job

    def register_by_corp_code(
        self, corp_code: str, fiscal_year: int, corp_name: str | None = None,
        stock_code: str | None = None, team: str | None = None, years: int = 5,
    ) -> tuple[Engagement, Job]:
        """corp_code 를 이미 아는 경우 회사식별(corpCode.xml 다운로드)을 건너뛰고 바로 수집·분석.

        웹 검색은 정적 목록에서 corp_code 를 선택해 넘기므로 대용량 corpCode.xml 을 런타임에
        받지 않는다(서버리스 대역폭 제약 회피). 회사명·업종은 수집 후 실제 값으로 보정된다.
        """
        engagement_id = content_id("ENG", corp_code, str(fiscal_year))
        engagement = Engagement(
            engagement_id=engagement_id, corp_code=corp_code,
            corp_name=corp_name or corp_code, stock_code=stock_code,
            ksic_code=None, fiscal_year=fiscal_year, team=team,
        )
        self.repo.save_engagement(engagement)
        job = self._collect_and_analyze(engagement, years=years, include_fees=False)
        return self.repo.get_engagement(engagement_id), job

    def refresh(self, engagement_id: str) -> Job:
        return self._collect_and_analyze(self._require(engagement_id), job_type=JobType.REANALYZE)

    # ── 수집 + 분석(모듈 1·2·3) ────────────────────────────────────────────────
    def _collect_and_analyze(self, engagement: Engagement, job_type: JobType = JobType.COLLECT,
                             years: int = 5, include_fees: bool = True) -> Job:
        job_id = content_id("JOB", engagement.engagement_id, job_type.value)
        job = Job(job_id=job_id, engagement_id=engagement.engagement_id, type=job_type,
                  status=JobStatus.RUNNING, progress=0.1)
        self.repo.save_job(job)
        try:
            record: CompanyRecord = self.adapter.fetch_company(
                engagement.corp_code, engagement.fiscal_year, years=years, include_fees=include_fees)
        except Exception as exc:  # noqa: BLE001 — 수집 실패는 job 상태로 표면화
            job.status = JobStatus.FAILED
            job.message = f"수집 실패: {exc}"
            self.repo.save_job(job)
            return job

        snapshot_id = content_id("SNAP", record.model_dump_json())
        self.repo.save_snapshot(snapshot_id, record.model_dump())
        # 수집된 실제 회사정보로 인게이지먼트 식별정보 보정(corp_code 직접 등록 경로 대비)
        if record.corp_name:
            engagement.corp_name = record.corp_name
        if record.ksic_code:
            engagement.ksic_code = record.ksic_code
        if record.stock_code:
            engagement.stock_code = record.stock_code
        engagement.snapshot_id = snapshot_id
        self.repo.save_engagement(engagement)

        ctx = AnalysisContext(
            engagement_id=engagement.engagement_id, corp_code=engagement.corp_code,
            fiscal_year=engagement.fiscal_year, snapshot_id=snapshot_id, rule_version=RULE_VERSION)

        signals: list[Signal] = []
        signals.extend(m1.analyze(record, ctx))
        signals.extend(m2.analyze(record, ctx))
        assessment, m3_signals = m3.analyze(record, ctx)
        signals.extend(m3_signals)

        self.repo.replace_signals(engagement.engagement_id, signals)
        self.repo.save_assessment(assessment)
        # 재수집 시 이전에 주입된 외부 공개정보(기사·감리사례)를 새 스냅샷 기준으로 재적용
        self._apply_external(engagement)

        # 파싱 이슈 → job 상태(SFR-C07)
        job.parse_issues = [ParseIssue(level=lv, where=w, detail=d) for (lv, w, d) in record.parse_issues]
        blocking = any(p.level == "blocking" for p in job.parse_issues)
        job.status = JobStatus.PARTIAL if job.parse_issues else JobStatus.SUCCEEDED
        if blocking:
            job.status = JobStatus.PARTIAL
        job.progress = 1.0
        job.message = f"신호 {len(signals)}건 · 계속기업 {assessment.overall_severity.value}"
        self.repo.save_job(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self.repo.get_job(job_id)

    def latest_job(self, engagement_id: str) -> Job | None:
        return self.repo.latest_job_for(engagement_id)

    # ── 조회(모듈 1·2·3) ───────────────────────────────────────────────────────
    def get_signals(self, engagement_id: str, module: str | None = None,
                    severity: str | None = None) -> list[Signal]:
        self._require(engagement_id)
        sigs = self.repo.list_signals(engagement_id)
        if module:
            sigs = [s for s in sigs if s.module == module]
        if severity:
            sigs = [s for s in sigs if s.severity.value == severity]
        return sorted(sigs, key=lambda s: (-s.severity.rank, s.module, s.category))

    def get_signal(self, signal_id: str) -> Signal | None:
        return self.repo.get_signal(signal_id)

    def get_going_concern(self, engagement_id: str) -> GoingConcernAssessment | None:
        self._require(engagement_id)
        return self.repo.get_assessment(engagement_id)

    def get_industry_profile(self, engagement_id: str | None = None, ksic: str | None = None) -> dict | None:
        if engagement_id:
            e = self._require(engagement_id)
            ksic = ksic or e.ksic_code
        return match_profile(ksic)

    # ── 외부 공개정보(기사·감리사례) 편입 ──────────────────────────────────────────
    def ingest_external(self, engagement_id: str, news: list[dict] | None = None,
                        review_cases: list[dict] | None = None) -> dict:
        """에이전트가 수집한 외부 공개정보를 신호로 편입한다(비신뢰 태깅, 판정 자동확정 안 함).

        기사는 WebSearch, 감리지적사례는 ifrs MCP(search_audit_case)에서 에이전트가 수집해
        전달한다. 페이로드는 저장되어 재수집 시 자동 재적용된다.
        """
        engagement = self._require(engagement_id)
        payload = {"news": news or [], "review_cases": review_cases or []}
        self.repo.save_external(engagement_id, payload)
        self._apply_external(engagement)
        ext = [s for s in self.repo.list_signals(engagement_id)
               if s.category in _EXTERNAL_CATEGORIES]
        return {
            "engagement_id": engagement_id,
            "ingested_news": len(payload["news"]),
            "ingested_review_cases": len(payload["review_cases"]),
            "external_signals": len(ext),
            "signal_ids": [s.signal_id for s in ext],
        }

    def _apply_external(self, engagement: Engagement) -> None:
        payload = self.repo.get_external(engagement.engagement_id)
        if not payload or not engagement.snapshot_id:
            return
        ctx = AnalysisContext(
            engagement_id=engagement.engagement_id, corp_code=engagement.corp_code,
            fiscal_year=engagement.fiscal_year, snapshot_id=engagement.snapshot_id,
            rule_version=RULE_VERSION)
        self.repo.remove_signals_by_category(engagement.engagement_id, _EXTERNAL_CATEGORIES)
        self.repo.add_signals(build_external_signals(payload, ctx))

    # ── 교차검증(모듈 4) — 멱등 계산, 저장 없음 ────────────────────────────────────
    def run_cross_validation(self, engagement_id: str) -> CrossValidationResult:
        e = self._require(engagement_id)
        snap = self.repo.get_snapshot(e.snapshot_id or "")
        if snap is None:
            raise EngagementNotFound(f"스냅샷 없음(수집 필요): {engagement_id}")
        record = CompanyRecord.model_validate(snap)
        signals = self.repo.list_signals(engagement_id)
        ctx = AnalysisContext(
            engagement_id=engagement_id, corp_code=e.corp_code, fiscal_year=e.fiscal_year,
            snapshot_id=e.snapshot_id, rule_version=RULE_VERSION)
        return m4.cross_validate(record, signals, ctx)

    # ── 메모(모듈 4) — 생성 시 핵심위험 확정·저장 ───────────────────────────────────
    def generate_memo_draft(self, engagement_id: str) -> Memo:
        e = self._require(engagement_id)
        record = CompanyRecord.model_validate(self.repo.get_snapshot(e.snapshot_id or ""))
        signals = self.repo.list_signals(engagement_id)
        assessment = self.repo.get_assessment(engagement_id)
        cross = self.run_cross_validation(engagement_id)
        self.repo.save_key_risks(engagement_id, cross.key_risks)
        memo = generate_memo(e, record, signals, assessment, cross)
        self.repo.save_memo(memo)
        return memo

    def get_memo(self, memo_id: str) -> Memo | None:
        return self.repo.get_memo(memo_id)

    def update_memo_section(self, memo_id: str, note: str, actor: str = "agent") -> Memo:
        """서술 보완(SFR-604). 근거 인용 검증 + 주입 방어 통과 필수. 승인본은 잠금."""
        memo = self.repo.get_memo(memo_id)
        if memo is None:
            raise KeyError(memo_id)
        if memo.status == MemoStatus.APPROVED:
            raise PermissionError("승인본은 수정 불가(회수 후 재작업 필요)")
        assert_no_injection(note)
        valid_ids = {s.signal_id for s in self.repo.list_signals(memo.engagement_id)}
        cited = assert_cited(note, valid_ids)
        memo.body_markdown += (
            f"\n\n> [분석자 서술 · 작성주체 {actor} · 근거 {', '.join(cited)}]\n> {note}\n")
        memo.version += 1
        self.repo.save_memo(memo)
        return memo

    def submit_memo_for_approval(self, memo_id: str) -> Memo:
        memo = self.repo.get_memo(memo_id)
        if memo is None:
            raise KeyError(memo_id)
        memo.status = MemoStatus.IN_REVIEW
        self.repo.save_memo(memo)
        return memo

    def approve_memo(self, memo_id: str, approver: str) -> Memo:
        """승인 — 웹 콘솔 전용 경로. MCP 도구로는 노출하지 않는다(SFR-604)."""
        memo = self.repo.get_memo(memo_id)
        if memo is None:
            raise KeyError(memo_id)
        if memo.status != MemoStatus.IN_REVIEW:
            raise PermissionError("승인 대기(IN_REVIEW) 상태에서만 승인 가능")
        memo.status = MemoStatus.APPROVED
        self.repo.save_memo(memo)
        return memo
