"""위험평가 메모 초안 생성 — 결정론적 템플릿 모드(SFR-404, 기본 경로).

모든 문장은 데이터·룰에서 유도된다. LLM 서술 모드는 이 산출물의 서술 개선에 한정되며
별도 경로다(참조구현 미포함). 면책 문안(SFR-405)은 편집 불가로 항상 삽입된다.
"""
from __future__ import annotations

from functools import lru_cache

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config import RULES_DIR, TEMPLATES_DIR
from ..dart.schema import CompanyRecord
from ..models import (
    CrossValidationResult,
    Engagement,
    GoingConcernAssessment,
    Memo,
    MemoStatus,
    Signal,
    content_id,
)
from ..modules.module2_industry import match_profile

# SFR-405 / RFP 10.3 — 편집 불가 고정 면책 문안
FIXED_DISCLAIMER = (
    "본 메모는 DART 공시 등 공개정보를 기반으로 시스템이 자동 생성한 **초안(draft)**이다. "
    "본 초안은 감사인의 전문가적 판단과 직업적 회의주의를 대체하지 않으며, "
    "**위험평가에 대한 최종 판단, 유의적 위험의 결정, 감사절차의 성격·시기·범위 결정은 "
    "업무수행이사와 감사팀이 수행한다.** 시스템 산출물을 이용하는 경우 감사기준서 500에 따라 "
    "정보의 목적적합성과 신뢰성을 평가하여야 한다."
)


@lru_cache(maxsize=1)
def _procedures() -> dict:
    return yaml.safe_load((RULES_DIR / "procedures.yaml").read_text(encoding="utf-8"))["procedures"]


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False,
        autoescape=False, keep_trailing_newline=True,
    )
    return env


def _counts(signals: list[Signal]) -> dict:
    out = {m: {"RED": 0, "YELLOW": 0, "GREEN": 0} for m in ("M1", "M2", "M3", "M4")}
    for s in signals:
        out[s.module][s.severity.value] += 1
    return out


def generate_memo(
    engagement: Engagement,
    record: CompanyRecord,
    signals: list[Signal],
    assessment: GoingConcernAssessment,
    cross: CrossValidationResult,
    mode: str = "template",
) -> Memo:
    industry = match_profile(record.ksic_code)
    kam_matched = {s.metrics.get("risk_id") for s in signals if s.category == "KAM_MATCH"}
    jet_trace = [
        {"rule_id": j.rule_id, "weight_multiplier": j.weight_multiplier,
         "reason": j.reason, "key_risk": kr.title}
        for kr in cross.key_risks for j in kr.jet_updates
    ]
    # 신호 정렬: 위험도 높은 순 → 안정적 표시(결정론)
    signals_sorted = sorted(signals, key=lambda s: (-s.severity.rank, s.module, s.category))

    body = _env().get_template("memo.md.j2").render(
        eng=engagement, industry=industry, gc=assessment,
        signals=signals_sorted, counts=_counts(signals),
        key_risks=cross.key_risks, procedures=_procedures(),
        kam_matched=kam_matched, jet_trace=jet_trace,
        parse_issues=[{"level": lv, "where": w, "detail": d} for (lv, w, d) in record.parse_issues],
        snapshot_id=cross.snapshot_id, rule_version=cross.rule_version,
        memo_mode=mode, generated_at="(생성 시각은 메모 메타에 기록)",
        disclaimer=FIXED_DISCLAIMER,
    )
    memo_id = content_id("MEMO", engagement.engagement_id, cross.snapshot_id, cross.rule_version)
    return Memo(
        memo_id=memo_id, engagement_id=engagement.engagement_id, version=1,
        status=MemoStatus.DRAFT, mode="template", body_markdown=body,
        snapshot_id=cross.snapshot_id, rule_version=cross.rule_version,
        key_risk_ids=[k.key_risk_id for k in cross.key_risks],
    )
