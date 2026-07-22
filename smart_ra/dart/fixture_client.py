"""Fixture 어댑터 — smart_ra/fixtures/*.json 의 샘플 회사 데이터를 반환한다.

DART 인증키 없이 전체 파이프라인을 재현하기 위한 참조구현용 클라이언트.
실제 배포에서는 rest_client.RestDartAdapter 로 교체된다.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import FIXTURES_DIR
from .adapter import CompanyIdentity
from .schema import CompanyRecord


@lru_cache(maxsize=1)
def _load_all() -> dict[str, CompanyRecord]:
    records: dict[str, CompanyRecord] = {}
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rec = CompanyRecord.model_validate(data)
        records[rec.corp_code] = rec
    return records


class FixtureDartAdapter:
    source = "fixture"

    def resolve_corp(self, query: str) -> CompanyIdentity | None:
        q = query.strip()
        for rec in _load_all().values():
            if q in (rec.corp_code, rec.stock_code, rec.corp_name):
                return CompanyIdentity(rec.corp_code, rec.corp_name, rec.stock_code, rec.ksic_code)
        # 부분 일치(법인명)
        for rec in _load_all().values():
            if q and q in rec.corp_name:
                return CompanyIdentity(rec.corp_code, rec.corp_name, rec.stock_code, rec.ksic_code)
        return None

    def fetch_company(self, corp_code: str, fiscal_year: int, years: int = 5) -> CompanyRecord:
        rec = _load_all().get(corp_code)
        if rec is None:
            raise KeyError(f"fixture 회사 없음: {corp_code}")
        # 원본 훼손 방지를 위해 복사본 반환
        return rec.model_copy(deep=True)

    @staticmethod
    def available() -> list[CompanyIdentity]:
        return [
            CompanyIdentity(r.corp_code, r.corp_name, r.stock_code, r.ksic_code)
            for r in _load_all().values()
        ]
