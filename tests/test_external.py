"""외부 공개정보(기사·감리사례) 편입 테스트."""
from smart_ra.service import SmartRaService


def _svc_with_engagement():
    svc = SmartRaService()  # 키 미설정 → fixture 어댑터
    eng, _ = svc.register_engagement("대양제조", 2023)
    return svc, eng


def test_ingest_external_creates_tagged_signals():
    svc, eng = _svc_with_engagement()
    res = svc.ingest_external(
        eng.engagement_id,
        news=[{"title": "전 임원 횡령 혐의", "snippet": "횡령",
               "url": "http://x/1", "source": "예시", "published": "2024-01-01"}],
        review_cases=[{"title": "재고자산 과소계상", "account": "재고자산",
                       "standards": ["K-IFRS 1002"], "year": "2022"}],
    )
    assert res["ingested_news"] == 1 and res["ingested_review_cases"] == 1
    sigs = svc.get_signals(eng.engagement_id)
    news = [s for s in sigs if s.category == "EXTERNAL_NEWS"]
    rev = [s for s in sigs if s.category == "REVIEW_PRECEDENT"]
    assert len(news) == 1 and len(rev) == 1
    # 기사=비신뢰, 감리사례=신뢰(금감원 공식)
    assert news[0].evidence[0].trust == "untrusted"
    assert rev[0].evidence[0].trust == "trusted"
    # 외부 정보만으로 RED 자동확정 금지 → YELLOW 상한(수동확인 경유)
    assert news[0].severity.value == "YELLOW"
    assert news[0].metrics["risk_keyword"] == "횡령"


def test_external_signals_survive_refresh():
    svc, eng = _svc_with_engagement()
    svc.ingest_external(eng.engagement_id, news=[{"title": "특허 소송", "snippet": "소송"}])
    before = [s for s in svc.get_signals(eng.engagement_id) if s.category == "EXTERNAL_NEWS"]
    svc.refresh(eng.engagement_id)  # 재수집이 외부 신호를 지우지 않아야 함
    after = [s for s in svc.get_signals(eng.engagement_id) if s.category == "EXTERNAL_NEWS"]
    assert len(before) == 1 and len(after) == 1


def test_ingest_is_idempotent():
    svc, eng = _svc_with_engagement()
    item = {"title": "횡령 혐의", "snippet": "횡령", "url": "http://x/1"}
    r1 = svc.ingest_external(eng.engagement_id, news=[item])
    r2 = svc.ingest_external(eng.engagement_id, news=[item])
    # 동일 입력·동일 스냅샷 → 동일 signal_id, 중복 누적 없음(재적용 멱등)
    assert r1["signal_ids"] == r2["signal_ids"]
    assert len([s for s in svc.get_signals(eng.engagement_id)
                if s.category == "EXTERNAL_NEWS"]) == 1
