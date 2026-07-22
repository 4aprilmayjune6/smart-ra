"""저장소 계층 — PoC용 인메모리 리포지토리.

RFP 아키텍처에서는 PostgreSQL(정형+JSONB)+오브젝트 스토리지가 목표지만(8.2),
참조구현은 동일한 리포지토리 인터페이스를 인메모리로 제공한다. 서비스 계층은
이 인터페이스에만 의존하므로 추후 PostgreSQL 구현으로 교체할 수 있다.

인게이지먼트 단위 데이터 격리(NFR-SEC-02, RLS)를 흉내내기 위해 조회는
engagement_id로 필터링한다.
"""
from __future__ import annotations

from .models import (
    Engagement,
    GoingConcernAssessment,
    Job,
    KeyRisk,
    Memo,
    Signal,
)


class Repository:
    def __init__(self) -> None:
        self._engagements: dict[str, Engagement] = {}
        self._jobs: dict[str, Job] = {}
        self._signals: dict[str, Signal] = {}
        self._assessments: dict[str, GoingConcernAssessment] = {}  # engagement_id → GCA
        self._key_risks: dict[str, KeyRisk] = {}
        self._memos: dict[str, Memo] = {}
        # 수집 원문/재무 스냅샷(부록 A snapshot). corp_code+snapshot_id → payload
        self._snapshots: dict[str, dict] = {}
        # 주입된 외부 공개정보(기사·감리사례) 원본. engagement_id → payload
        self._external: dict[str, dict] = {}

    # ── Engagement ──────────────────────────────────────────────────────────
    def save_engagement(self, e: Engagement) -> None:
        self._engagements[e.engagement_id] = e

    def get_engagement(self, engagement_id: str) -> Engagement | None:
        return self._engagements.get(engagement_id)

    def list_engagements(self) -> list[Engagement]:
        return sorted(self._engagements.values(), key=lambda e: e.created_at)

    # ── Job ─────────────────────────────────────────────────────────────────
    def save_job(self, j: Job) -> None:
        self._jobs[j.job_id] = j

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def latest_job_for(self, engagement_id: str) -> Job | None:
        jobs = [j for j in self._jobs.values() if j.engagement_id == engagement_id]
        return max(jobs, key=lambda j: j.created_at) if jobs else None

    # ── Signal ──────────────────────────────────────────────────────────────
    def replace_signals(self, engagement_id: str, signals: list[Signal]) -> None:
        """스냅샷 단위 재분석 시 해당 인게이지먼트 신호를 원자적으로 교체."""
        for sid in [s for s, v in self._signals.items() if v.engagement_id == engagement_id]:
            del self._signals[sid]
        for s in signals:
            self._signals[s.signal_id] = s

    def add_signals(self, signals: list[Signal]) -> None:
        """기존 신호를 유지한 채 추가(외부 신호 편입용)."""
        for s in signals:
            self._signals[s.signal_id] = s

    def remove_signals_by_category(self, engagement_id: str, categories: tuple[str, ...]) -> None:
        for sid in [s for s, v in self._signals.items()
                    if v.engagement_id == engagement_id and v.category in categories]:
            del self._signals[sid]

    def get_signal(self, signal_id: str) -> Signal | None:
        return self._signals.get(signal_id)

    def list_signals(self, engagement_id: str) -> list[Signal]:
        return [s for s in self._signals.values() if s.engagement_id == engagement_id]

    # ── Going concern assessment ─────────────────────────────────────────────
    def save_assessment(self, a: GoingConcernAssessment) -> None:
        self._assessments[a.engagement_id] = a

    def get_assessment(self, engagement_id: str) -> GoingConcernAssessment | None:
        return self._assessments.get(engagement_id)

    # ── Key risk ────────────────────────────────────────────────────────────
    def save_key_risks(self, engagement_id: str, risks: list[KeyRisk]) -> None:
        for kid in [k for k, v in self._key_risks.items() if v.engagement_id == engagement_id]:
            del self._key_risks[kid]
        for r in risks:
            self._key_risks[r.key_risk_id] = r

    def list_key_risks(self, engagement_id: str) -> list[KeyRisk]:
        return [r for r in self._key_risks.values() if r.engagement_id == engagement_id]

    # ── Memo ────────────────────────────────────────────────────────────────
    def save_memo(self, m: Memo) -> None:
        self._memos[m.memo_id] = m

    def get_memo(self, memo_id: str) -> Memo | None:
        return self._memos.get(memo_id)

    # ── Snapshot(수집 데이터) ─────────────────────────────────────────────────
    def save_snapshot(self, snapshot_id: str, payload: dict) -> None:
        self._snapshots[snapshot_id] = payload

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        return self._snapshots.get(snapshot_id)

    # ── 외부 공개정보(기사·감리사례) ────────────────────────────────────────────
    def save_external(self, engagement_id: str, payload: dict) -> None:
        self._external[engagement_id] = payload

    def get_external(self, engagement_id: str) -> dict | None:
        return self._external.get(engagement_id)
