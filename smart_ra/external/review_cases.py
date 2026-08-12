"""감리지적 선례 매칭 — 회사 업종(KSIC→industry_id)에 맞는 금감원 감리사례를 반환.

감리지적사례는 공개 REST API가 없고 ifrs MCP(에이전트 전용)로만 조회되므로, 대표 선례를
`data/review_cases.json` 정적 번들로 두고 업종별로 결정론 매칭한다(M2.REVIEW_PRECEDENT).
반환값은 ingest_external(review_cases=...) 페이로드(ReviewCase) 형식이다. 외부 trusted 신호로
태깅되며 판정 자동확정 없이 YELLOW 상한(SFR-606). 실제 사용 전 SME 검수 대상.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import DATA_DIR
from ..modules.module2_industry import match_profile


@lru_cache(maxsize=1)
def _all_cases() -> list[dict]:
    data = json.loads((DATA_DIR / "review_cases.json").read_text(encoding="utf-8"))
    return data.get("cases", [])


def match_review_cases(record, limit: int = 3) -> list[dict]:
    """회사 업종에 매칭되는 감리 선례를 ReviewCase 페이로드 리스트로 반환(없으면 빈 리스트)."""
    profile = match_profile(getattr(record, "ksic_code", None))
    if not profile:
        return []
    industry_id = profile.get("industry_id")
    out: list[dict] = []
    for c in _all_cases():
        if industry_id in c.get("industries", []):
            out.append({k: v for k, v in c.items() if k != "industries"})
        if len(out) >= limit:
            break
    return out
