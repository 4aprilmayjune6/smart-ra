"""DART 수집 어댑터 계층.

RFP 8.1 원칙 2: 핵심 수집의 계약 기준은 공식 OpenDART REST 사양이며, 커뮤니티
라이브러리(OpenDartReader/dart-fss)는 얇은 어댑터 뒤의 보조 레이어로만 둔다.
참조구현은 어댑터 인터페이스(get_adapter)를 두고 fixture/rest 구현을 교체 가능하게 한다.
"""

from .adapter import DartAdapter, get_adapter
from .schema import AuditRecord, CompanyRecord, DisclosureRecord, FinancialRecord

__all__ = [
    "DartAdapter",
    "get_adapter",
    "CompanyRecord",
    "DisclosureRecord",
    "AuditRecord",
    "FinancialRecord",
]
