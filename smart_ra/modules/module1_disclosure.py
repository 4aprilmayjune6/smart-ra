"""모듈 1 — DART 공시 위험시그널 추출 (SFR-101~110).

산출: 위험 키워드, 감사인 변경, 감사의견·강조사항, 정정공시 빈도,
비감사보수 비중, 전기 KAM. 모든 신호는 근거(evidence)를 포함한다(NFR-REL-01).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import yaml

from ..config import RULES_DIR
from ..dart.schema import CompanyRecord, DisclosureRecord
from ..models import Evidence, Severity, Signal, content_id
from . import AnalysisContext

_SCANNED_TYPES = {"B", "E", "I", "F"}  # 주요사항·기타·거래소·외부감사관련
CORRECTION_THRESHOLD_12M = 3
NON_AUDIT_FEE_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def _keyword_config() -> dict:
    return yaml.safe_load((RULES_DIR / "keywords.yaml").read_text(encoding="utf-8"))


def _parse_dt(s: str) -> date | None:
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None


def _mk_signal(ctx: AnalysisContext, category: str, severity: Severity, score: float,
               title: str, evidence: list[Evidence], seed_extra: str = "", **kw) -> Signal:
    seed = f"{ctx.engagement_id}|{ctx.snapshot_id}|M1|{category}|{seed_extra}"
    return Signal(
        signal_id=content_id("SIG", seed),
        engagement_id=ctx.engagement_id,
        corp_code=ctx.corp_code,
        module="M1",
        category=category,
        severity=severity,
        score_contribution=score,
        title=title,
        evidence=evidence,
        rule_version=ctx.rule_version,
        snapshot_id=ctx.snapshot_id,
        **kw,
    )


def _find_matches(text: str, synonyms: list[str], excludes: list[str]) -> list[str]:
    """부정 문맥(excludes)이 매칭 직후 40자 내에 없으면 유효 매칭으로 본다(SFR-101)."""
    hits: list[str] = []
    for syn in synonyms:
        start = 0
        while (idx := text.find(syn, start)) != -1:
            window = text[idx: idx + len(syn) + 40]
            if not any(ex in window for ex in excludes):
                ctx_lo = max(0, idx - 15)
                hits.append(text[ctx_lo: idx + len(syn) + 25].strip())
            start = idx + len(syn)
    return hits


def _scan_keywords(record: CompanyRecord, ctx: AnalysisContext) -> list[Signal]:
    cfg = _keyword_config()
    excludes = cfg.get("global_excludes", [])
    signals: list[Signal] = []
    for kw in cfg["keywords"]:
        evidence: list[Evidence] = []
        for d in record.disclosures:
            if d.pblntf_ty not in _SCANNED_TYPES:
                continue
            text = f"{d.report_nm}\n{d.body}"
            hits = _find_matches(text, kw["synonyms"], excludes)
            if hits:
                evidence.append(Evidence(
                    type="disclosure", rcept_no=d.rcept_no, url=Evidence.dart_url(d.rcept_no),
                    excerpt=hits[0], trust="untrusted",
                ))
        if evidence:
            sev = Severity(kw["severity"])
            signals.append(_mk_signal(
                ctx, "RISK_KEYWORD",  # 단일 카테고리, keyword_id는 metrics로 구분
                sev, 15.0 if sev is Severity.RED else 8.0,
                f"위험 키워드 '{kw['label']}' 공시 {len(evidence)}건 탐지",
                evidence, seed_extra=kw["id"], standard_refs=kw.get("standard_refs", []),
                metrics={"keyword_id": kw["id"], "keyword_label": kw["label"], "hits": len(evidence)},
            ))
    return signals


def _auditor_change(record: CompanyRecord, ctx: AnalysisContext) -> Signal | None:
    window = range(ctx.fiscal_year - 3, ctx.fiscal_year)  # 최근 3개 회계연도(전기 이전)
    changes = [a for a in record.audits if a.fiscal_year in window and a.change_type == "free"]
    designated = [a for a in record.audits if a.fiscal_year in window and a.change_type == "designated"]
    if not changes:
        return None
    ev = [Evidence(type="disclosure", rcept_no=a.rcept_no, url=Evidence.dart_url(a.rcept_no or ""),
                   excerpt=f"{a.fiscal_year}: {a.auditor} (자유선임 변경)", trust="untrusted")
          for a in changes]
    note = f" (지정감사 {len(designated)}건 별도)" if designated else ""
    return _mk_signal(
        ctx, "AUDITOR_CHANGE", Severity.YELLOW, 10.0,
        f"최근 3년 내 감사인 자유선임 변경 {len(changes)}회{note}", ev,
        standard_refs=["KSA 315", "KSA 220"],
        metrics={"free_changes_3y": len(changes), "designated_3y": len(designated)},
    )


def _audit_opinion(record: CompanyRecord, ctx: AnalysisContext) -> Signal | None:
    prior = record.audit_for(ctx.fiscal_year - 1)
    if prior is None:
        return None
    ev = [Evidence(type="disclosure", rcept_no=prior.rcept_no, url=Evidence.dart_url(prior.rcept_no or ""),
                   excerpt=f"{prior.fiscal_year} 감사의견: {prior.opinion}"
                           + ("; " + "; ".join(prior.emphasis_paras) if prior.emphasis_paras else ""),
                   trust="untrusted")]
    if prior.opinion != "적정":
        return _mk_signal(ctx, "AUDIT_OPINION", Severity.RED, 20.0,
                          f"전기 감사의견 비적정: {prior.opinion}", ev,
                          standard_refs=["KSA 705"], metrics={"opinion": prior.opinion})
    if prior.emphasis_paras or prior.going_concern_para:
        return _mk_signal(ctx, "AUDIT_EMPHASIS", Severity.YELLOW, 8.0,
                          "전기 감사보고서 강조사항/계속기업 불확실성 문단 존재", ev,
                          standard_refs=["KSA 706", "KSA 570"],
                          metrics={"going_concern_para": prior.going_concern_para})
    return None


def _correction_freq(record: CompanyRecord, ctx: AnalysisContext) -> Signal | None:
    dates = [d for d in (record.disclosures) if _parse_dt(d.rcept_dt)]
    if not dates:
        return None
    ref = max(_parse_dt(d.rcept_dt) for d in dates)  # 기준일 = 최신 공시일(결정론)
    lo = ref - timedelta(days=365)
    corrected = [d for d in record.disclosures
                 if d.corrected and (dt := _parse_dt(d.rcept_dt)) and lo <= dt <= ref]
    if len(corrected) < CORRECTION_THRESHOLD_12M:
        return None
    ev = [Evidence(type="disclosure", rcept_no=d.rcept_no, url=Evidence.dart_url(d.rcept_no),
                   excerpt=f"{d.report_nm} — {d.correction_reason}", trust="untrusted")
          for d in corrected]
    return _mk_signal(ctx, "CORRECTION_FREQ", Severity.YELLOW, 8.0,
                      f"최근 12개월 정정공시 {len(corrected)}건(신뢰성 저하 정황)", ev,
                      standard_refs=["KSA 315"], metrics={"count_12m": len(corrected)})


def _non_audit_fee(record: CompanyRecord, ctx: AnalysisContext) -> Signal | None:
    prior = record.audit_for(ctx.fiscal_year - 1)
    if prior is None or not prior.audit_fee or prior.non_audit_fee is None:
        return None
    ratio = prior.non_audit_fee / prior.audit_fee
    if ratio < NON_AUDIT_FEE_THRESHOLD:
        return None
    ev = [Evidence(type="disclosure", rcept_no=prior.rcept_no, url=Evidence.dart_url(prior.rcept_no or ""),
                   excerpt=f"감사보수 {prior.audit_fee} / 비감사보수 {prior.non_audit_fee} (백만원)",
                   trust="untrusted")]
    return _mk_signal(ctx, "NON_AUDIT_FEE", Severity.YELLOW, 6.0,
                      f"비감사용역 보수 비중 {ratio:.0%}(독립성 위험)", ev,
                      standard_refs=["KSA 220"], metrics={"ratio": round(ratio, 3)})


def _prior_kam(record: CompanyRecord, ctx: AnalysisContext) -> Signal | None:
    prior = record.audit_for(ctx.fiscal_year - 1)
    if prior is None or not prior.kam:
        return None
    ev = [Evidence(type="disclosure", rcept_no=prior.rcept_no, url=Evidence.dart_url(prior.rcept_no or ""),
                   excerpt="전기 KAM: " + "; ".join(prior.kam), trust="untrusted")]
    return _mk_signal(ctx, "PRIOR_KAM", Severity.GREEN, 0.0,
                      f"전기 핵심감사사항(KAM) {len(prior.kam)}건 — 당기 중점검토 영역", ev,
                      standard_refs=["KSA 701"], metrics={"kam": prior.kam})


def analyze(record: CompanyRecord, ctx: AnalysisContext) -> list[Signal]:
    signals: list[Signal] = []
    signals.extend(_scan_keywords(record, ctx))
    for fn in (_auditor_change, _audit_opinion, _correction_freq, _non_audit_fee, _prior_kam):
        sig = fn(record, ctx)
        if sig is not None:
            signals.append(sig)
    return signals
