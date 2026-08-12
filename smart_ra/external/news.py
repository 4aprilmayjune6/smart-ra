"""외부 기사 수집 — Google 뉴스 RSS(키·등록 불필요, 무료). 서버리스에서 호출한다.

회사명으로 최근 한국어 기사를 RSS로 받아 NewsHit 페이로드(dict)로 반환한다. 인증키가 필요
없으므로 배포 즉시 동작한다. 수집된 기사는 외부 비신뢰(untrusted) 신호로 태깅되며 자동 RED
확정 없이 YELLOW 상한이 적용된다(SFR-606, external/sources.py) — 판정은 서버 결정론, 기사는
참고·수동확인 대상이다. 실패 시 빈 리스트(메모 생성에 영향 없음).
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from html import unescape
from xml.etree import ElementTree as ET

from .sources import NEWS_RISK_KEYWORDS

_ENDPOINT = "https://news.google.com/rss/search"
_TAG = re.compile(r"<[^>]+>")
# 위험신호 관련 키워드(external/sources.py 와 동일 사전) — 검색·필터 공통 사용.
_RISK_KEYWORDS = list(NEWS_RISK_KEYWORDS.keys())


def _clean(s: str | None) -> str:
    return unescape(_TAG.sub("", s or "")).strip()


def _fmt_date(pub: str | None) -> str:
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def fetch_news(query: str, limit: int = 6, timeout: float = 8.0,
               risk_only: bool = True) -> list[dict]:
    """회사명으로 Google 뉴스(한국어) 기사를 NewsHit 페이로드 리스트로 반환.

    risk_only=True(기본) 면 감사위험 관련 기사만 남긴다: ①검색어를 위험 키워드로 좁히고
    (`"회사명" (소송 OR 제재 OR 횡령 …)`), ②제목에 위험 키워드가 있는 기사만 통과시킨다.
    위험 관련 기사가 없으면 빈 리스트(=위험 기사 없음, 정상 신호).
    """
    query = query.strip()
    if not query:
        return []

    if risk_only:
        q = f'"{query}" ({" OR ".join(_RISK_KEYWORDS)})'
    else:
        q = query
    params = urllib.parse.urlencode(
        {"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    req = urllib.request.Request(
        f"{_ENDPOINT}?{params}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; smart-ra/0.1)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            xml = r.read()
        root = ET.fromstring(xml)
    except Exception:  # noqa: BLE001 — 뉴스 실패는 무시(부가정보)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    out: list[dict] = []
    for item in channel.findall("item"):
        title = _clean(item.findtext("title"))
        src_el = item.find("source")
        source = _clean(src_el.text) if src_el is not None else ""
        # Google 뉴스 제목은 흔히 "제목 - 매체명" → 매체명 꼬리 제거
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        if not title:
            continue
        # 위험 필터: 제목에 위험 키워드가 하나 이상 있어야 통과(검색어가 이미 회사로 한정됨).
        # 회사명 문자열 일치는 요구하지 않음 — 통칭이 다른 경우(NAVER→네이버 등) 과다 필터 방지.
        if risk_only and not any(kw in title for kw in _RISK_KEYWORDS):
            continue
        out.append({
            "title": title,
            "url": (item.findtext("link") or "").strip(),
            "source": source,
            "published": _fmt_date(item.findtext("pubDate")),
            "snippet": "",  # RSS description 은 관련기사 목록이라 노이즈 → 제목·매체·일자만 사용
        })
        if len(out) >= limit:
            break
    return out
