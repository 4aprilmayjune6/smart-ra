"""파이프라인 검증 — 결정론 재현성, 하드룰, 교차검증, 근거 강제, 산업 왜곡 보정."""
from __future__ import annotations

import pytest

from smart_ra.models import Severity
from smart_ra.service import SmartRaService


def _analyze(query: str, year: int = 2024):
    svc = SmartRaService()
    engagement, job = svc.register_engagement(query, year)
    return svc, engagement, job


# ── 결정론 재현성 (NFR-REL-02) ────────────────────────────────────────────────
def test_deterministic_reproducibility():
    svc1, e1, _ = _analyze("한빛건설")
    svc2, e2, _ = _analyze("한빛건설")
    # 동일 fixture → 동일 스냅샷 ID
    assert e1.snapshot_id == e2.snapshot_id
    ids1 = sorted(s.signal_id for s in svc1.get_signals(e1.engagement_id))
    ids2 = sorted(s.signal_id for s in svc2.get_signals(e2.engagement_id))
    assert ids1 == ids2
    # 메모 본문도 동일(생성 시각 제외 — 템플릿에 실시간 시각 미포함)
    m1 = svc1.generate_memo_draft(e1.engagement_id)
    m2 = svc2.generate_memo_draft(e2.engagement_id)
    assert m1.memo_id == m2.memo_id
    assert m1.body_markdown == m2.body_markdown


# ── 하드룰: 전기 계속기업 불확실성 문단 → 즉시 RED (부록 B) ───────────────────────
def test_going_concern_hard_rule_red():
    svc, e, _ = _analyze("한빛건설")
    gc = svc.get_going_concern(e.engagement_id)
    assert gc.overall_severity is Severity.RED
    assert "계속기업 관련 중요한 불확실성" in gc.hard_rule_triggered


def test_healthy_company_green():
    svc, e, _ = _analyze("대양제조")
    gc = svc.get_going_concern(e.engagement_id)
    assert gc.overall_severity is Severity.GREEN
    assert gc.hard_rule_triggered is None


# ── 산업 왜곡 보정: 수익 창출 전 바이오는 현금 runway로 YELLOW (SFR-302) ───────────
def test_pre_revenue_cash_runway_yellow():
    svc, e, _ = _analyze("제노바이오")
    gc = svc.get_going_concern(e.engagement_id)
    assert gc.overall_severity is Severity.YELLOW
    names = [i.name for i in gc.indicators]
    assert "현금 runway" in names  # 이자보상배율 대신 runway 사용
    assert "이자보상배율" not in names


# ── 교차검증: 계속기업 압박 + 공시 신뢰성 저하 → XV-001 (SFR-401) ─────────────────
def test_cross_validation_xv001_fires():
    svc, e, _ = _analyze("한빛건설")
    cross = svc.run_cross_validation(e.engagement_id)
    rule_ids = {kr.rule_id for kr in cross.key_risks}
    assert "XV-001" in rule_ids  # 계속기업 압박 하 이익조정
    assert "XV-002" in rule_ids  # 횡령·배임 부정
    # 유의적 위험 후보가 앞에 정렬
    assert cross.key_risks[0].significant_risk_candidate is True


def test_cross_validation_baseline_management_override_always():
    # 건전 회사도 통제무력화(상시 유의적 위험)는 항상 포함(KSA 240)
    svc, e, _ = _analyze("대양제조")
    cross = svc.run_cross_validation(e.engagement_id)
    assert any(kr.rule_id == "XV-BASE-01" for kr in cross.key_risks)


# ── 315→240 흐름: 핵심위험 → JET 룰 가중치 조정 ──────────────────────────────────
def test_jet_update_traceability():
    svc, e, _ = _analyze("한빛건설")
    cross = svc.run_cross_validation(e.engagement_id)
    jet = [j for kr in cross.key_risks for j in kr.jet_updates]
    assert jet, "핵심위험에서 JET 룰 조정이 파생되어야 한다(315→240)"
    # 모든 JET 조정은 원천 핵심위험을 통해 추적 가능
    for kr in cross.key_risks:
        for j in kr.jet_updates:
            assert j.weight_multiplier >= 1.0


# ── 근거 강제 (NFR-REL-01): 모든 신호는 evidence >= 1 ────────────────────────────
@pytest.mark.parametrize("query", ["한빛건설", "대양제조", "제노바이오"])
def test_all_signals_have_evidence(query):
    svc, e, _ = _analyze(query)
    for s in svc.get_signals(e.engagement_id):
        assert len(s.evidence) >= 1, f"{s.key} 신호에 근거가 없습니다"


# ── 키워드 부정 문맥 제외 (SFR-101) ────────────────────────────────────────────
def test_keyword_negation_excluded():
    # 대양제조 공시에는 위험 키워드가 없어 RISK_KEYWORD 신호가 없어야 함
    svc, e, _ = _analyze("대양제조")
    kws = [s for s in svc.get_signals(e.engagement_id) if s.category == "RISK_KEYWORD"]
    assert kws == []


# ── 메모 고정 면책 문안 (SFR-405) ──────────────────────────────────────────────
def test_memo_fixed_disclaimer_present():
    svc, e, _ = _analyze("한빛건설")
    memo = svc.generate_memo_draft(e.engagement_id)
    assert "감사기준서 500" in memo.body_markdown
    assert "최종 판단, 유의적 위험의 결정" in memo.body_markdown
