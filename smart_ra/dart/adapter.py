"""DART 어댑터 인터페이스 및 팩토리."""
from __future__ import annotations

from typing import Protocol

from ..config import settings
from .schema import CompanyRecord


class CompanyIdentity:
    def __init__(self, corp_code: str, corp_name: str, stock_code: str | None, ksic_code: str | None):
        self.corp_code = corp_code
        self.corp_name = corp_name
        self.stock_code = stock_code
        self.ksic_code = ksic_code


class DartAdapter(Protocol):
    """수집 어댑터 계약. fixture/rest 구현이 이 인터페이스를 만족한다."""

    source: str

    def resolve_corp(self, query: str) -> CompanyIdentity | None:
        """법인명 또는 종목코드로 회사를 식별한다(corpCode.xml / company.json)."""
        ...

    def fetch_company(self, corp_code: str, fiscal_year: int, years: int = 5) -> CompanyRecord:
        """공시목록·원문·재무·감사정보를 수집해 정규화한다."""
        ...


def get_adapter(source: str | None = None) -> DartAdapter:
    """설정에 따라 어댑터를 반환한다.

    - fixture: 샘플 데이터(DART 인증키 불필요) — 참조구현 기본
    - rest: 실제 OpenDART REST(인증키 필요)
    """
    src = source or settings.effective_dart_source()
    if src == "rest":
        from .rest_client import RestDartAdapter

        return RestDartAdapter()
    from .fixture_client import FixtureDartAdapter

    return FixtureDartAdapter()
