"""수집 데이터 정규화 스키마 — fixture/REST 어댑터의 공통 출력 계약.

OpenDART 원천 API(IR-01)의 필드를 감사 위험분석에 필요한 최소 집합으로 정규화한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DisclosureRecord(BaseModel):
    """공시 1건 — list.json + document.xml(본문) 정규화."""

    rcept_no: str
    report_nm: str
    # 공시유형: A 정기 / B 주요사항 / E 기타 / F 외부감사관련 / I 거래소
    pblntf_ty: Literal["A", "B", "E", "F", "I"]
    rcept_dt: str  # YYYYMMDD
    corrected: bool = False  # [기재정정]/[첨부정정] 여부
    correction_reason: str = ""
    body: str = ""  # 본문 발췌(원문). 외부 유래 → 비신뢰 텍스트


class AuditRecord(BaseModel):
    """연도별 감사 정보 — 정기보고서 주요정보(감사인/의견/보수) + 감사보고서 파싱."""

    fiscal_year: int
    auditor: str
    opinion: Literal["적정", "한정", "부적정", "의견거절"] = "적정"
    # 감사인 변경 성격: none 미변경 / free 자유선임 변경 / designated 지정
    change_type: Literal["none", "free", "designated"] = "none"
    going_concern_para: bool = False  # 계속기업 관련 중요한 불확실성 문단 존재
    emphasis_paras: list[str] = Field(default_factory=list)  # 강조사항
    kam: list[str] = Field(default_factory=list)  # 핵심감사사항(KSA 701)
    audit_fee: float | None = None  # 감사보수(백만원)
    non_audit_fee: float | None = None  # 비감사용역 보수(백만원)
    rcept_no: str | None = None  # 근거 공시(사업보고서/감사보고서)


class FinancialRecord(BaseModel):
    """연도별 재무 계정(백만원). 결측은 None. 연결 우선."""

    year: int
    basis: Literal["CFS", "OFS"] = "CFS"
    revenue: float | None = None
    operating_income: float | None = None
    interest_expense: float | None = None
    operating_cash_flow: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    capital_stock: float | None = None  # 자본금
    cash: float | None = None  # 현금및현금성자산
    rcept_no: str | None = None


class CompanyRecord(BaseModel):
    """단일 회사·단일 인게이지먼트 수집 결과."""

    corp_code: str
    corp_name: str
    stock_code: str | None = None
    ksic_code: str | None = None
    disclosures: list[DisclosureRecord] = Field(default_factory=list)
    audits: list[AuditRecord] = Field(default_factory=list)
    financials: list[FinancialRecord] = Field(default_factory=list)
    # 수집 시 재현 불가/부분 실패를 기록(SFR-C07). (level, where, detail)
    parse_issues: list[tuple[str, str, str]] = Field(default_factory=list)

    def audit_for(self, year: int) -> AuditRecord | None:
        return next((a for a in self.audits if a.fiscal_year == year), None)

    def financials_sorted(self) -> list[FinancialRecord]:
        return sorted(self.financials, key=lambda f: f.year)
