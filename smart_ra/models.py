"""코어 도메인 모델 — RFP 부록 A(Signal 공통 스키마) 및 관련 산출물.

결정론 원칙(NFR-REL-02): signal_id·key_risk_id는 내용 해시 기반으로 생성하여
동일 입력·동일 룰 버전에서 항상 동일한 식별자가 나오도록 한다(순번 카운터 미사용).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# 열거형 — 등급 표기(RFP 1.5): 내부 코드는 텍스트, 이모지는 화면 표시 전용
# ─────────────────────────────────────────────────────────────────────────────
class Severity(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"

    @property
    def emoji(self) -> str:
        return {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢"}[self.value]

    @property
    def rank(self) -> int:
        return {"GREEN": 0, "YELLOW": 1, "RED": 2}[self.value]


Module = Literal["M1", "M2", "M3", "M4"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_id(prefix: str, *parts: str) -> str:
    """내용 기반 결정론적 ID. 재현성(NFR-REL-02)을 위해 순번 대신 해시 12자리 사용."""
    digest = _sha256("|".join(parts))[:12]
    return f"{prefix}-{digest}"


# ─────────────────────────────────────────────────────────────────────────────
# 근거(Evidence) — 모든 신호는 evidence >= 1 강제(NFR-REL-01)
# ─────────────────────────────────────────────────────────────────────────────
class Evidence(BaseModel):
    type: str = "disclosure"  # disclosure | financial | note
    rcept_no: str | None = None
    url: str | None = None
    excerpt: str = ""
    sha256: str | None = None
    # 외부 유래 텍스트는 비신뢰 라벨(SFR-606). 간접 프롬프트 주입 대응.
    trust: Literal["trusted", "untrusted"] = "untrusted"

    @staticmethod
    def dart_url(rcept_no: str) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


class Review(BaseModel):
    state: Literal["UNREVIEWED", "REVIEWED", "DISMISSED"] = "UNREVIEWED"
    reviewer: str | None = None
    note: str | None = None


class Signal(BaseModel):
    """RFP 부록 A. 모듈 1~3의 정규화 산출물."""

    signal_id: str
    engagement_id: str
    corp_code: str
    module: Module
    category: str  # 예: AUDITOR_CHANGE, CORRECTION_FREQ, OVERALL
    severity: Severity
    score_contribution: float = 0.0
    title: str
    evidence: list[Evidence] = Field(default_factory=list)
    standard_refs: list[str] = Field(default_factory=list)
    related_assertions: list[str] = Field(default_factory=list)
    # 위험도(severity)와 분리된 추출 신뢰도(RFP 부록 A confidence)
    confidence: float = 1.0
    # 룰 파라미터 매칭용 정량 지표(예: {"count_12m": 3}). 교차검증 DSL이 참조.
    metrics: dict[str, Any] = Field(default_factory=dict)
    detected_at: str = Field(default_factory=utc_now_iso)
    rule_version: str
    snapshot_id: str
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    review: Review = Field(default_factory=Review)

    @property
    def key(self) -> str:
        """교차검증 DSL 매칭 키. 예: 'M1.AUDITOR_CHANGE'."""
        return f"{self.module}.{self.category}"


# ─────────────────────────────────────────────────────────────────────────────
# 계속기업 평가(모듈 3) — 부록 B
# ─────────────────────────────────────────────────────────────────────────────
class IndicatorResult(BaseModel):
    name: str
    values: dict[str, float | None] = Field(default_factory=dict)  # 연도 → 값
    severity: Severity
    score: float
    reason: str  # 근거 자동 문장(SFR-304)
    ksa570_tag: str | None = None  # KSA 570 A3 사건·상황 예시 매핑


class GoingConcernAssessment(BaseModel):
    engagement_id: str
    corp_code: str
    overall_severity: Severity
    overall_score: float
    hard_rule_triggered: str | None = None  # 하드룰 발동 사유(있으면 즉시 RED)
    indicators: list[IndicatorResult] = Field(default_factory=list)
    snapshot_id: str
    rule_version: str


# ─────────────────────────────────────────────────────────────────────────────
# 핵심위험(모듈 4)
# ─────────────────────────────────────────────────────────────────────────────
class JetUpdate(BaseModel):
    rule_id: str
    weight_multiplier: float
    reason: str = ""


class KeyRisk(BaseModel):
    key_risk_id: str
    engagement_id: str
    rule_id: str  # 발동한 교차검증 룰(XV-xxx) 또는 baseline
    title: str
    significant_risk_candidate: bool = False
    accounts: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)  # 권고 후속 감사절차
    jet_updates: list[JetUpdate] = Field(default_factory=list)
    source_signals: list[str] = Field(default_factory=list)  # 수렴 근거 signal_id
    rationale: str = ""


class CrossValidationResult(BaseModel):
    """run_cross_validation 산출(멱등 계산, 저장은 generate_memo_draft가 수행)."""

    engagement_id: str
    snapshot_id: str
    rule_version: str
    key_risks: list[KeyRisk] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# 메모(모듈 4)
# ─────────────────────────────────────────────────────────────────────────────
class MemoStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"


class Memo(BaseModel):
    memo_id: str
    engagement_id: str
    version: int = 1
    status: MemoStatus = MemoStatus.DRAFT
    mode: Literal["template", "llm"] = "template"
    body_markdown: str
    # 생성 메타데이터 각인(SFR-404): 재현성·감리 대응
    snapshot_id: str
    rule_version: str
    generated_at: str = Field(default_factory=utc_now_iso)
    key_risk_ids: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# 인게이지먼트 / 작업(Job) / 수집 데이터
# ─────────────────────────────────────────────────────────────────────────────
class Engagement(BaseModel):
    engagement_id: str
    corp_code: str
    corp_name: str
    stock_code: str | None = None
    ksic_code: str | None = None
    fiscal_year: int
    team: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    snapshot_id: str | None = None  # 마지막 수집 스냅샷


class JobType(str, Enum):
    COLLECT = "COLLECT"
    REANALYZE = "REANALYZE"
    EXPORT = "EXPORT"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"  # 부분 성공(파싱 실패 항목 존재, SFR-C07)
    FAILED = "FAILED"


class ParseIssue(BaseModel):
    """파싱 실패 처리 표준(SFR-C07). 등급별로 수동확인 태스크화."""

    level: Literal["blocking", "warning", "informational"]
    where: str
    detail: str


class Job(BaseModel):
    job_id: str
    engagement_id: str
    type: JobType
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    parse_issues: list[ParseIssue] = Field(default_factory=list)
    message: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
