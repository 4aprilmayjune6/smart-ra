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

_ENDPOINT = "https://news.google.com/rss/search"
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str | None) -> str:
    return unescape(_TAG.sub("", s or "")).strip()


def _fmt_date(pub: str | None) -> str:
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def fetch_news(query: str, limit: int = 6, timeout: float = 8.0) -> list[dict]:
    """회사명으로 Google 뉴스(한국어) 최근 기사를 NewsHit 페이로드 리스트로 반환."""
    if not query.strip():
        return []
    params = urllib.parse.urlencode(
        {"q": query.strip(), "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
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
    for item in channel.findall("item")[:limit]:
        title = _clean(item.findtext("title"))
        src_el = item.find("source")
        source = _clean(src_el.text) if src_el is not None else ""
        # Google 뉴스 제목은 흔히 "제목 - 매체명" → 매체명 꼬리 제거
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": (item.findtext("link") or "").strip(),
            "source": source,
            "published": _fmt_date(item.findtext("pubDate")),
            "snippet": "",  # RSS description 은 관련기사 목록이라 노이즈 → 제목·매체·일자만 사용
        })
    return out
