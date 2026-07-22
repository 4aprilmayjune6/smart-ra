"""위험평가 메모 → HTML 감사 워킹페이퍼 출력 (SFR-408 내보내기).

memo.generator(markdown)와 동일한 결정론 데이터·고정 면책 문안을 사용하되, 조서 편철·
인쇄에 적합한 단일 컬럼 문서로 렌더링한다.
"""
from __future__ import annotations

from functools import lru_cache

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from ..config import RULES_DIR, TEMPLATES_DIR
from ..dart.schema import CompanyRecord
from ..models import CrossValidationResult, Engagement, GoingConcernAssessment, Signal
from ..modules.module2_industry import match_profile
from .generator import FIXED_DISCLAIMER


@lru_cache(maxsize=1)
def _procedures() -> dict:
    return yaml.safe_load((RULES_DIR / "procedures.yaml").read_text(encoding="utf-8"))["procedures"]


def _won(x) -> str:
    return f"{x:,.0f}" if x is not None else "—"


def _bold(text: str) -> Markup:
    """고정 면책 문안의 **강조** 마커를 <strong>으로 변환(신뢰 텍스트, 안전)."""
    parts = text.split("**")
    return Markup("".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts)))


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined, autoescape=True, keep_trailing_newline=True,
    )
    env.filters["won"] = _won
    return env


def _counts(signals: list[Signal]) -> dict:
    out = {m: {"RED": 0, "YELLOW": 0, "GREEN": 0} for m in ("M1", "M2", "M3", "M4")}
    for s in signals:
        out[s.module][s.severity.value] += 1
    return out


def generate_memo_html(
    engagement: Engagement,
    record: CompanyRecord,
    signals: list[Signal],
    assessment: GoingConcernAssessment,
    cross: CrossValidationResult,
    generated_at: str = "",
) -> str:
    industry = match_profile(record.ksic_code)
    kam_matched = {s.metrics.get("risk_id") for s in signals if s.category == "KAM_MATCH"}
    jet_trace = [
        {"rule_id": j.rule_id, "mult": j.weight_multiplier, "reason": j.reason, "kr": kr.title}
        for kr in cross.key_risks for j in kr.jet_updates
    ]
    signals_sorted = sorted(signals, key=lambda s: (-s.severity.rank, s.module, s.category))
    return _env().get_template("memo.html.j2").render(
        eng=engagement, industry=industry, gc=assessment,
        signals=signals_sorted, counts=_counts(signals),
        key_risks=cross.key_risks, procedures=_procedures(),
        kam_matched=kam_matched, jet_trace=jet_trace,
        financials=[f.model_dump() for f in record.financials_sorted()],
        parse_issues=[{"level": lv, "where": w, "detail": d} for (lv, w, d) in record.parse_issues],
        snapshot_id=cross.snapshot_id, rule_version=cross.rule_version,
        generated_at=generated_at, disclaimer=_bold(FIXED_DISCLAIMER),
        source="OpenDART 실데이터" if record.corp_code[:2] != "90" else "샘플(fixture) 데이터",
    )
