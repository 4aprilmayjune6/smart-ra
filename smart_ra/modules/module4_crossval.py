"""모듈 4 — 교차검증 룰엔진 → 핵심위험 도출 (SFR-401~403).

모듈 1·2·3 신호를 선언적 룰(cross_validation.yaml)로 교차검증하여 핵심위험(KeyRisk)을
도출한다. 산업 위험맵(모듈2)의 유의적 위험 기본 항목도 핵심위험 카드로 편입한다.
LLM 미사용 — 전량 결정론(SFR-602). 메모 생성은 memo.generator가 담당.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from ..config import RULES_DIR
from ..dart.schema import CompanyRecord
from ..models import CrossValidationResult, JetUpdate, KeyRisk, Signal, content_id
from . import AnalysisContext
from .module2_industry import match_profile

_CMP = re.compile(r"^(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)$")


@lru_cache(maxsize=1)
def _ruleset() -> dict:
    return yaml.safe_load((RULES_DIR / "cross_validation.yaml").read_text(encoding="utf-8"))


def _num_ok(actual, op: str, num: float) -> bool:
    try:
        a = float(actual)
    except (TypeError, ValueError):
        return False
    return {">=": a >= num, "<=": a <= num, "==": a == num, ">": a > num, "<": a < num}[op]


def _params_ok(params: dict, metrics: dict) -> bool:
    for k, expected in params.items():
        if k.endswith("_in"):
            if metrics.get(k[:-3]) not in (expected or []):
                return False
        elif isinstance(expected, str) and (m := _CMP.match(expected)):
            if not _num_ok(metrics.get(k), m.group(1), float(m.group(2))):
                return False
        else:
            if metrics.get(k) != expected:
                return False
    return True


def _eval(cond: dict, signals: list[Signal]) -> tuple[bool, list[Signal]]:
    if cond.get("always"):
        return True, []
    if "all" in cond:
        contributing: list[Signal] = []
        for sub in cond["all"]:
            ok, c = _eval(sub, signals)
            if not ok:
                return False, []
            contributing.extend(c)
        return True, contributing
    if "any" in cond:
        contributing = []
        matched = False
        for sub in cond["any"]:
            ok, c = _eval(sub, signals)
            if ok:
                matched = True
                contributing.extend(c)
        return matched, contributing
    # leaf
    key = cond["signal"]
    sev_in = cond.get("severity_in")
    params = cond.get("params", {})
    hits = [s for s in signals if s.key == key
            and (not sev_in or s.severity.value in sev_in)
            and _params_ok(params, s.metrics)]
    return bool(hits), hits


def _key_risk_from_rule(rule: dict, contributing: list[Signal], ctx: AnalysisContext) -> KeyRisk:
    kr = rule["then"]["key_risk"]
    titles = ", ".join(s.title for s in contributing) or "상시 적용"
    rationale = kr.get("rationale_template", "").replace("{signals}", titles)
    return KeyRisk(
        key_risk_id=content_id("KR", ctx.engagement_id, ctx.snapshot_id, rule["rule_id"]),
        engagement_id=ctx.engagement_id, rule_id=rule["rule_id"], title=kr["title"],
        significant_risk_candidate=kr.get("significant_risk_candidate", False),
        accounts=kr.get("accounts", []), assertions=kr.get("assertions", []),
        standards=kr.get("standards", []), procedures=kr.get("procedures", []),
        jet_updates=[JetUpdate(**j) for j in kr.get("jet_updates", [])],
        source_signals=[s.signal_id for s in contributing], rationale=rationale,
    )


def _industry_key_risks(record: CompanyRecord, signals: list[Signal], ctx: AnalysisContext) -> list[KeyRisk]:
    profile = match_profile(record.ksic_code)
    if not profile:
        return []
    kam_matched = {s.metrics.get("risk_id") for s in signals if s.category == "KAM_MATCH"}
    industry_sig = next((s.signal_id for s in signals if s.category == "INDUSTRY"), None)
    out: list[KeyRisk] = []
    for item in profile["risk_items"]:
        if not (item.get("significant_risk_default") or item["risk_id"] in kam_matched):
            continue
        src = [industry_sig] if industry_sig else []
        src += [s.signal_id for s in signals
                if s.category == "KAM_MATCH" and s.metrics.get("risk_id") == item["risk_id"]]
        std = item["standards"].get("kifrs", []) + item["standards"].get("ksa", [])
        note = " (전기 KAM 일치)" if item["risk_id"] in kam_matched else ""
        out.append(KeyRisk(
            key_risk_id=content_id("KR", ctx.engagement_id, ctx.snapshot_id, item["risk_id"]),
            engagement_id=ctx.engagement_id, rule_id=item["risk_id"],
            title=f"[산업] {item['account']} — {item['issue']}",
            significant_risk_candidate=item.get("significant_risk_default", False),
            accounts=[item["account"]], assertions=item.get("assertions", []),
            standards=std, procedures=item.get("planned_procedures", []),
            jet_updates=[JetUpdate(rule_id=j["rule_id"], weight_multiplier=j.get("base_weight", 1.0),
                                   reason=j.get("desc", "")) for j in item.get("je_rules", [])],
            source_signals=[s for s in src if s], rationale=f"{profile['name']} 산업 고유 위험{note}",
        ))
    return out


def cross_validate(record: CompanyRecord, signals: list[Signal], ctx: AnalysisContext) -> CrossValidationResult:
    key_risks: list[KeyRisk] = []
    for rule in _ruleset()["rules"]:
        ok, contributing = _eval(rule["when"], signals)
        if ok:
            key_risks.append(_key_risk_from_rule(rule, contributing, ctx))
    key_risks.extend(_industry_key_risks(record, signals, ctx))

    # 유의적 위험 후보를 앞으로(안정 정렬 — 동일 순위는 도출 순서 유지)
    key_risks.sort(key=lambda k: (not k.significant_risk_candidate,))
    return CrossValidationResult(
        engagement_id=ctx.engagement_id, snapshot_id=ctx.snapshot_id,
        rule_version=ctx.rule_version, key_risks=key_risks)
