"""모듈 2 — 산업별 위험매핑 (SFR-201~206).

KSIC 코드 → industry_risk_map.json 프로파일 매핑. 고위험계정→경영진 주장→기준서→
연동 전표룰(JET)→권고 절차의 체인을 제공하고, 전기 KAM과 산업 위험항목을 매칭한다.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import DATA_DIR
from ..dart.schema import CompanyRecord
from ..models import Evidence, Severity, Signal, content_id
from . import AnalysisContext


@lru_cache(maxsize=1)
def load_map() -> dict:
    return json.loads((DATA_DIR / "industry_risk_map.json").read_text(encoding="utf-8"))


def match_profile(ksic_code: str | None) -> dict | None:
    """KSIC 접두 매칭. 가장 긴 접두가 우선."""
    if not ksic_code:
        return None
    best: tuple[int, dict] | None = None
    for ind in load_map()["industries"]:
        for pfx in ind["ksic_prefixes"]:
            if ksic_code.startswith(pfx):
                if best is None or len(pfx) > best[0]:
                    best = (len(pfx), ind)
    return best[1] if best else None


def _mk_signal(ctx: AnalysisContext, category: str, severity: Severity, title: str,
               evidence: list[Evidence], seed_extra: str = "", **kw) -> Signal:
    seed = f"{ctx.engagement_id}|{ctx.snapshot_id}|M2|{category}|{seed_extra}"
    return Signal(
        signal_id=content_id("SIG", seed), engagement_id=ctx.engagement_id,
        corp_code=ctx.corp_code, module="M2", category=category, severity=severity,
        title=title, evidence=evidence, rule_version=ctx.rule_version,
        snapshot_id=ctx.snapshot_id, **kw,
    )


def analyze(record: CompanyRecord, ctx: AnalysisContext) -> list[Signal]:
    profile = match_profile(record.ksic_code)
    if profile is None:
        return [_mk_signal(
            ctx, "INDUSTRY_UNMAPPED", Severity.YELLOW,
            f"KSIC '{record.ksic_code}' 산업 프로파일 미매핑 — 수동 지정 필요",
            [Evidence(type="note", excerpt=f"KSIC {record.ksic_code} 매핑 실패", trust="trusted")],
            metrics={"ksic": record.ksic_code},
        )]

    signals: list[Signal] = []
    risk_ids = [r["risk_id"] for r in profile["risk_items"]]
    signals.append(_mk_signal(
        ctx, "INDUSTRY", Severity.GREEN,
        f"산업 프로파일: {profile['name']} — 고유 위험항목 {len(risk_ids)}건",
        [Evidence(type="note", trust="trusted",
                  excerpt=f"KSIC {record.ksic_code} → {profile['name']}(industry_risk_map)")],
        metrics={"industry_id": profile["industry_id"], "name": profile["name"], "risk_ids": risk_ids},
    ))

    # 전기 KAM ↔ 산업 위험항목 매칭(SFR-107 연계)
    prior = record.audit_for(ctx.fiscal_year - 1)
    prior_kam = " ".join(prior.kam) if prior else ""
    for item in profile["risk_items"]:
        matched = [k for k in item.get("kam_keywords", []) if k in prior_kam]
        if matched:
            signals.append(_mk_signal(
                ctx, "KAM_MATCH", Severity.YELLOW,
                f"전기 KAM이 산업 위험 '{item['risk_id']}'({item['account']})과 일치 — 당기 중점",
                [Evidence(type="note", excerpt=f"전기 KAM: {prior_kam}", trust="untrusted")],
                seed_extra=item["risk_id"],
                standard_refs=item["standards"].get("ksa", []),
                metrics={"risk_id": item["risk_id"], "matched_keywords": matched},
            ))
    return signals
