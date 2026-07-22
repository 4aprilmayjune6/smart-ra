"""모듈 1~4 결정론 분석 엔진.

RFP 8.1 원칙 1(설명가능성): 판정은 선언적 룰 + 공개 산식으로만 이루어지며,
LLM/블랙박스 ML을 사용하지 않는다. 동일 스냅샷·룰 버전 → 동일 산출(NFR-REL-02).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisContext:
    engagement_id: str
    corp_code: str
    fiscal_year: int
    snapshot_id: str
    rule_version: str
