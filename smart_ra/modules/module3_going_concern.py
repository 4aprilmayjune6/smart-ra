"""모듈 3 — 계속기업 불확실성 스코어링 (SFR-301~306, 부록 B).

지표별 구간점수 × 가중치 → 위험점수(0~100) → 신호등. 하드룰(완전자본잠식·전기 계속기업
불확실성 문단·부도/회생 공시)은 즉시 RED. 수익 창출 전 단계 기업(바이오 등)은 현금 runway
관점으로 보정한다(SFR-302). 모든 판정에 근거 문장(SFR-304)과 KSA 570 A3 태그를 부착한다.
"""
from __future__ import annotations

from ..dart.schema import CompanyRecord, FinancialRecord
from ..models import (
    Evidence,
    GoingConcernAssessment,
    IndicatorResult,
    Severity,
    Signal,
    content_id,
)
from . import AnalysisContext

# 표준 가중치(부록 B 예시). 합계 100.
WEIGHTS = {"ocf_trend": 25, "interest_coverage": 25, "capital_impairment": 20,
           "debt_ratio": 15, "current_ratio": 15}
# 수익 창출 전 단계 기업용 가중치(이자보상 제외, 현금 runway 추가).
WEIGHTS_PRE_REVENUE = {"cash_runway": 40, "capital_impairment": 20, "debt_ratio": 15,
                       "current_ratio": 15, "ocf_trend": 10}
_SEV_FACTOR = {Severity.GREEN: 0.0, Severity.YELLOW: 0.5, Severity.RED: 1.0}
_HARD_RULE_KEYWORDS = ("부도", "회생", "파산", "영업정지", "은행거래정지", "당좌거래정지")


def _band(score: float) -> Severity:
    if score >= 70:
        return Severity.RED
    if score >= 40:
        return Severity.YELLOW
    return Severity.GREEN


def _is_pre_revenue(fins: list[FinancialRecord]) -> bool:
    latest = fins[-1]
    return (latest.operating_income is not None and latest.operating_income < 0
            and latest.revenue is not None and latest.revenue < abs(latest.operating_income))


def _ocf_trend(fins: list[FinancialRecord], pre_revenue: bool) -> IndicatorResult:
    vals = {str(f.year): f.operating_cash_flow for f in fins}
    consec = 0
    for f in reversed(fins):
        if f.operating_cash_flow is not None and f.operating_cash_flow < 0:
            consec += 1
        else:
            break
    if consec >= 3:
        sev = Severity.RED
    elif consec == 2:
        sev = Severity.YELLOW
    else:
        sev = Severity.GREEN
    # 수익 창출 전 단계는 영업현금 유출이 예정된 특성 → YELLOW로 상한(SFR-302)
    if pre_revenue and sev is Severity.RED:
        sev = Severity.YELLOW
    reason = f"영업활동현금흐름 {consec}년 연속 음수" if consec else "영업활동현금흐름 양호"
    return IndicatorResult(name="영업현금흐름 추세", values=vals, severity=sev,
                           score=WEIGHTS.get("ocf_trend", 0) * _SEV_FACTOR[sev],
                           reason=reason, ksa570_tag="영업활동 순현금유출 지속")


def _interest_coverage(fins: list[FinancialRecord]) -> IndicatorResult:
    def cov(f: FinancialRecord) -> float | None:
        if f.operating_income is None or not f.interest_expense:
            return None
        return f.operating_income / f.interest_expense
    vals = {str(f.year): cov(f) for f in fins}
    recent = [cov(f) for f in fins[-3:] if cov(f) is not None]
    latest = cov(fins[-1])
    if len(recent) >= 3 and all(c < 1 for c in recent):
        sev, reason = Severity.RED, "이자보상배율 3개년 연속 1 미만(한계기업)"
    elif latest is not None and latest < 1:
        sev, reason = Severity.YELLOW, "당기 이자보상배율 1 미만"
    else:
        sev, reason = Severity.GREEN, "이자보상배율 양호"
    if latest is not None:
        reason += f" (당기 {latest:.2f})"
    return IndicatorResult(name="이자보상배율", values=vals, severity=sev,
                           score=WEIGHTS["interest_coverage"] * _SEV_FACTOR[sev],
                           reason=reason, ksa570_tag="차입금 상환 능력 저하")


def _current_ratio(fins: list[FinancialRecord]) -> IndicatorResult:
    f = fins[-1]
    ratio = (f.current_assets / f.current_liabilities
             if f.current_assets is not None and f.current_liabilities else None)
    if ratio is None:
        sev, reason = Severity.YELLOW, "유동비율 산출 불가(데이터 결측)"
    elif ratio < 0.5:
        sev, reason = Severity.RED, f"유동비율 {ratio:.0%}(50% 미만)"
    elif ratio < 1.0:
        sev, reason = Severity.YELLOW, f"유동비율 {ratio:.0%}(100% 미만)"
    else:
        sev, reason = Severity.GREEN, f"유동비율 {ratio:.0%}"
    return IndicatorResult(name="유동비율", values={str(f.year): ratio}, severity=sev,
                           score=WEIGHTS["current_ratio"] * _SEV_FACTOR[sev],
                           reason=reason, ksa570_tag="단기 유동성 부족")


def _debt_ratio(fins: list[FinancialRecord]) -> IndicatorResult:
    f = fins[-1]
    eq = f.total_equity
    if eq is None or f.total_liabilities is None:
        sev, reason, ratio = Severity.YELLOW, "부채비율 산출 불가(데이터 결측)", None
    elif eq <= 0:
        sev, reason, ratio = Severity.RED, "자본총계 음수(자본잠식)", None
    else:
        ratio = f.total_liabilities / eq
        if ratio > 4.0:
            sev, reason = Severity.RED, f"부채비율 {ratio:.0%}(400% 초과)"
        elif ratio > 2.0:
            sev, reason = Severity.YELLOW, f"부채비율 {ratio:.0%}(200% 초과)"
        else:
            sev, reason = Severity.GREEN, f"부채비율 {ratio:.0%}"
    return IndicatorResult(name="부채비율", values={str(f.year): ratio}, severity=sev,
                           score=WEIGHTS["debt_ratio"] * _SEV_FACTOR[sev],
                           reason=reason, ksa570_tag="과도한 재무 레버리지")


def _capital_impairment(fins: list[FinancialRecord]) -> tuple[IndicatorResult, bool]:
    f = fins[-1]
    complete = f.total_equity is not None and f.total_equity <= 0
    if f.capital_stock and f.total_equity is not None:
        rate = (f.capital_stock - f.total_equity) / f.capital_stock
    else:
        rate = None
    if complete:
        sev, reason = Severity.RED, "완전자본잠식(자본총계 ≤ 0)"
    elif rate is not None and rate >= 0.5:
        sev, reason = Severity.RED, f"자본잠식률 {rate:.0%}(50% 이상, 관리종목 요건 수준)"
    elif rate is not None and rate > 0:
        sev, reason = Severity.YELLOW, f"부분 자본잠식(잠식률 {rate:.0%})"
    else:
        sev, reason = Severity.GREEN, "자본잠식 없음"
    ind = IndicatorResult(name="자본잠식", values={str(f.year): rate}, severity=sev,
                          score=WEIGHTS["capital_impairment"] * _SEV_FACTOR[sev],
                          reason=reason, ksa570_tag="자본잠식")
    return ind, complete


def _cash_runway(fins: list[FinancialRecord]) -> IndicatorResult:
    f = fins[-1]
    outflow = -f.operating_cash_flow if f.operating_cash_flow and f.operating_cash_flow < 0 else 0
    if not outflow or f.cash is None:
        sev, reason, runway = Severity.GREEN, "영업현금 유출 없음(runway 충분)", None
    else:
        runway = f.cash / outflow
        if runway < 1:
            sev, reason = Severity.RED, f"현금 runway {runway:.1f}년(1년 미만)"
        elif runway < 2:
            sev, reason = Severity.YELLOW, f"현금 runway {runway:.1f}년(2년 미만)"
        else:
            sev, reason = Severity.GREEN, f"현금 runway {runway:.1f}년"
    return IndicatorResult(name="현금 runway", values={str(f.year): runway}, severity=sev,
                           score=WEIGHTS_PRE_REVENUE["cash_runway"] * _SEV_FACTOR[sev],
                           reason=reason, ksa570_tag="현금 소진(자금조달 의존)")


def _hard_rule(record: CompanyRecord, ctx: AnalysisContext, complete_impairment: bool) -> str | None:
    if complete_impairment:
        return "완전자본잠식"
    prior = record.audit_for(ctx.fiscal_year - 1)
    if prior and prior.going_concern_para:
        return "전기 감사보고서 계속기업 관련 중요한 불확실성 문단"
    for d in record.disclosures:
        text = f"{d.report_nm}{d.body}"
        if any(k in text for k in _HARD_RULE_KEYWORDS):
            hit = next(k for k in _HARD_RULE_KEYWORDS if k in text)
            return f"부도·회생·영업정지 등 공시({hit})"
    return None


def analyze(record: CompanyRecord, ctx: AnalysisContext) -> tuple[GoingConcernAssessment, list[Signal]]:
    fins = record.financials_sorted()
    if not fins:
        assessment = GoingConcernAssessment(
            engagement_id=ctx.engagement_id, corp_code=ctx.corp_code,
            overall_severity=Severity.YELLOW, overall_score=0.0,
            hard_rule_triggered="재무데이터 없음(수동확인 필요)",
            snapshot_id=ctx.snapshot_id, rule_version=ctx.rule_version)
        return assessment, [_overall_signal(assessment, ctx)]

    pre_revenue = _is_pre_revenue(fins)
    cap_ind, complete = _capital_impairment(fins)
    indicators = [_ocf_trend(fins, pre_revenue), cap_ind, _debt_ratio(fins), _current_ratio(fins)]
    if pre_revenue:
        indicators.append(_cash_runway(fins))
    else:
        indicators.append(_interest_coverage(fins))

    score = sum(i.score for i in indicators)
    severity = _band(score)

    hard = _hard_rule(record, ctx, complete)
    if hard:
        severity = Severity.RED
    elif pre_revenue:
        # 현금 runway를 소프트 플로어로 적용(계속기업 관점)
        runway_sev = next((i.severity for i in indicators if i.name == "현금 runway"), Severity.GREEN)
        if runway_sev.rank > severity.rank:
            severity = runway_sev

    assessment = GoingConcernAssessment(
        engagement_id=ctx.engagement_id, corp_code=ctx.corp_code,
        overall_severity=severity, overall_score=round(score, 1),
        hard_rule_triggered=hard, indicators=indicators,
        snapshot_id=ctx.snapshot_id, rule_version=ctx.rule_version)
    return assessment, [_overall_signal(assessment, ctx)]


def _overall_signal(a: GoingConcernAssessment, ctx: AnalysisContext) -> Signal:
    reasons = "; ".join(f"{i.name}: {i.reason}" for i in a.indicators) or (a.hard_rule_triggered or "")
    ev = [Evidence(type="financial", excerpt=reasons, trust="trusted")]
    title = f"계속기업 위험 종합: {a.overall_severity.value} (점수 {a.overall_score})"
    if a.hard_rule_triggered:
        title += f" — 하드룰: {a.hard_rule_triggered}"
    return Signal(
        signal_id=content_id("SIG", f"{ctx.engagement_id}|{ctx.snapshot_id}|M3|OVERALL"),
        engagement_id=ctx.engagement_id, corp_code=ctx.corp_code, module="M3",
        category="OVERALL", severity=a.overall_severity, score_contribution=a.overall_score,
        title=title, evidence=ev, standard_refs=["KSA 570"],
        metrics={"score": a.overall_score, "hard_rule": a.hard_rule_triggered or ""},
        rule_version=ctx.rule_version, snapshot_id=ctx.snapshot_id)
