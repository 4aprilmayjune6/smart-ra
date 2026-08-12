"""네이버 뉴스 검색 API → 기사(NewsHit) 수집. 서버리스(api/analyze)에서 호출한다.

자격증명(NAVER_CLIENT_ID / NAVER_CLIENT_SECRET)은 환경변수로만 읽고 코드·응답에 노출하지
않는다. 미설정 시 빈 리스트를 반환해 메모 생성은 그대로 진행된다(뉴스는 부가정보).

수집된 기사는 외부 비신뢰(untrusted) 신호로 태깅되며 자동 RED 확정 없이 YELLOW 상한이
적용된다(SFR-606, external/sources.py). 즉 판정은 서버 결정론, 기사는 참고·수동확인 대상이다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from html import unescape

_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str | None) -> str:
    return unescape(_TAG.sub("", s or "")).strip()


def _fmt_date(pub: str) -> str:
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return pub or ""


def fetch_news(query: str, display: int = 5, sort: str = "date", timeout: float = 8.0) -> list[dict]:
    """회사명으로 최근 기사를 검색해 NewsHit 페이로드(dict) 리스트로 반환.

    자격증명 미설정·오류 시 빈 리스트(메모 생성에 영향 없음).
    """
    cid = os.environ.get("NAVER_CLIENT_ID")
    sec = os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and sec and query.strip()):
        return []

    url = _ENDPOINT + "?" + urllib.parse.urlencode(
        {"query": query.strip(), "display": max(1, min(display, 10)), "sort": sort})
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec,
        "User-Agent": "smart-ra/0.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — 뉴스 실패는 무시(부가정보)
        return []

    out: list[dict] = []
    for it in data.get("items", []):
        link = it.get("originallink") or it.get("link") or ""
        source = ""
        try:
            source = urllib.parse.urlparse(link).netloc.replace("www.", "")
        except ValueError:
            source = ""
        out.append({
            "title": _clean(it.get("title")),
            "url": link,
            "source": source,
            "published": _fmt_date(it.get("pubDate", "")),
            "snippet": _clean(it.get("description")),
        })
    return out
