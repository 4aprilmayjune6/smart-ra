"""외부 공개정보 → 정규화 신호 변환(결정론).

에이전트가 주입한 기사·감리사례를 Signal(부록 A)로 변환한다. 외부 유래이므로
evidence.trust 는 기사=untrusted, 감리사례=trusted(금감원 공식 기록)로 구분하되,
severity 는 외부 정보 자동 확정 방지를 위해 YELLOW 상한을 적용한다(수동확인 경유).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import Evidence, Severity, Signal, content_id
from ..modules import AnalysisContext

# 기사 제목·요약에서 탐지할 부정·위험 키워드 → 위험 힌트(RED 후보라도 외부는 YELLOW 상한).
NEWS_RISK_KEYWORDS: dict[str, str] = {
    "횡령": "RED", "배임": "RED", "분식회계": "RED", "분식": "RED", "주가조작": "RED",
    "내부자거래": "RED", "압수수색": "RED", "구속": "RED", "기소": "RED", "상장폐지": "RED",
    "회생": "RED", "파산": "RED", "부도": "RED", "영업정지": "RED",
    "소송": "YELLOW", "고발": "YELLOW", "제재": "YELLOW", "과징금": "YELLOW",
    "감자": "YELLOW", "불성실공시": "YELLOW", "리콜": "YELLOW", "담합": "YELLOW",
}


class NewsHit(BaseModel):
    """에이전트(WebSearch)가 수집해 주입하는 기사 1건."""

    title: str
    url: str | None = None
    source: str = ""          # 매체명
    published: str = ""       # 발행일(YYYY-MM-DD 등)
    snippet: str = ""         # 요약·발췌


class ReviewCase(BaseModel):
    """에이전트(ifrs MCP search_audit_case)가 수집해 주입하는 감리지적사례 1건."""

    title: str
    case_id: str = ""                                    # 금감원 공개번호
    year: str = ""                                       # 결정연도
    standards: list[str] = Field(default_factory=list)   # 예: ["K-IFRS 1115", "KSA 240"]
    account: str = ""                                    # 관련 계정(있으면)
    issue: str = ""                                      # 지적 요지
    url: str | None = None


def _news_hint(hit: NewsHit) -> tuple[Severity, str]:
    text = f"{hit.title} {hit.snippet}"
    for kw, hint in NEWS_RISK_KEYWORDS.items():
        if kw in text:
            # 외부 untrusted → RED 후보라도 YELLOW 상한(수동확인 경유, SFR-606)
            return Severity.YELLOW, kw
    return Severity.YELLOW, ""


def news_signals(hits: list[NewsHit], ctx: AnalysisContext) -> list[Signal]:
    out: list[Signal] = []
    for h in hits:
        sev, kw = _news_hint(h)
        excerpt = h.title + (f" — {h.snippet}" if h.snippet else "")
        ev = [Evidence(type="news", url=h.url, excerpt=excerpt, trust="untrusted")]
        title = f"외부 기사: {h.title[:70]}" + (f" [키워드 '{kw}']" if kw else "")
        out.append(Signal(
            signal_id=content_id("SIG", f"{ctx.engagement_id}|{ctx.snapshot_id}|M1|EXTERNAL_NEWS|{h.url or h.title}"),
            engagement_id=ctx.engagement_id, corp_code=ctx.corp_code, module="M1",
            category="EXTERNAL_NEWS", severity=sev, score_contribution=0.0, title=title,
            evidence=ev, standard_refs=["KSA 315", "KSA 240"], confidence=0.5,
            metrics={"source": h.source, "published": h.published,
                     "risk_keyword": kw, "risk_hint": NEWS_RISK_KEYWORDS.get(kw, "")},
            rule_version=ctx.rule_version, snapshot_id=ctx.snapshot_id,
        ))
    return out


def review_signals(cases: list[ReviewCase], ctx: AnalysisContext) -> list[Signal]:
    out: list[Signal] = []
    for c in cases:
        excerpt = f"[{c.year}] {c.title}" + (f" — {c.issue}" if c.issue else "")
        ev = [Evidence(type="review_case", url=c.url, excerpt=excerpt, trust="trusted")]
        title = f"감리지적 선례: {c.title[:60]}" + (f" (계정 {c.account})" if c.account else "")
        out.append(Signal(
            signal_id=content_id("SIG", f"{ctx.engagement_id}|{ctx.snapshot_id}|M2|REVIEW_PRECEDENT|{c.case_id or c.title}"),
            engagement_id=ctx.engagement_id, corp_code=ctx.corp_code, module="M2",
            category="REVIEW_PRECEDENT", severity=Severity.YELLOW, score_contribution=0.0, title=title,
            evidence=ev, standard_refs=c.standards, confidence=0.7,
            metrics={"case_id": c.case_id, "year": c.year, "account": c.account, "standards": c.standards},
            rule_version=ctx.rule_version, snapshot_id=ctx.snapshot_id,
        ))
    return out


def build_external_signals(payload: dict, ctx: AnalysisContext) -> list[Signal]:
    """ingest 페이로드({"news": [...], "review_cases": [...]}) → 신호 리스트."""
    news = [NewsHit.model_validate(x) for x in payload.get("news", [])]
    cases = [ReviewCase.model_validate(x) for x in payload.get("review_cases", [])]
    return news_signals(news, ctx) + review_signals(cases, ctx)
