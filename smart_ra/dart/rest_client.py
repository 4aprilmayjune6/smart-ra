"""OpenDART REST 어댑터 — 공식 API 사양 기반(IR-01).

인증키(SMARTRA_DART_API_KEY)가 설정된 경우 활성화된다. 구조화 엔드포인트
(재무제표·감사의견·보수)를 우선 사용하고, 비정형 감사보고서 원문 파싱이 필요한
항목(감사인 변경 이력 등)은 best-effort로 처리하며 실패 시 parse_issues에 기록한다(SFR-C07).

주의: 정확한 엔드포인트·필드는 구현 착수 시점의 OpenDART 개발가이드 최신본으로
확정하고 계약 테스트(contract test)로 고정해야 한다(NFR-MNT-03).
"""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import httpx

from ..config import settings
from .adapter import CompanyIdentity
from .schema import AuditRecord, CompanyRecord, DisclosureRecord, FinancialRecord

_REPRT_ANNUAL = "11011"  # 사업보고서

# 재무 계정명 → CompanyRecord 필드 매핑(표준계정 매핑, SFR-302)
_ACCOUNT_MAP = {
    "매출액": "revenue",
    "수익(매출액)": "revenue",
    "영업이익": "operating_income",
    "영업이익(손실)": "operating_income",
    "이자비용": "interest_expense",
    "영업활동현금흐름": "operating_cash_flow",
    "영업활동으로인한현금흐름": "operating_cash_flow",
    "유동자산": "current_assets",
    "유동부채": "current_liabilities",
    "자산총계": "total_assets",
    "부채총계": "total_liabilities",
    "자본총계": "total_equity",
    "자본금": "capital_stock",
    "현금및현금성자산": "cash",
}


def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s) / 1_000_000  # 원 → 백만원
    except ValueError:
        return None


class RestDartAdapter:
    source = "rest"

    def __init__(self) -> None:
        if not settings.dart_api_key:
            raise RuntimeError("SMARTRA_DART_API_KEY 미설정 — rest 어댑터 사용 불가")
        self._key = settings.dart_api_key
        self._base = settings.dart_base_url
        self._client = httpx.Client(timeout=30.0)

    def _get(self, endpoint: str, **params) -> httpx.Response:
        params["crtfc_key"] = self._key
        return self._client.get(f"{self._base}/{endpoint}", params=params)

    # ── 회사 식별 ─────────────────────────────────────────────────────────────
    def resolve_corp(self, query: str) -> CompanyIdentity | None:
        # corpCode.xml (zip) 에서 매칭. 실제 운영은 일 1회 캐시 갱신(SFR-C02).
        resp = self._get("corpCode.xml")
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml = zf.read(zf.namelist()[0])
        root = ET.fromstring(xml)
        q = query.strip()
        match = None
        for item in root.iter("list"):
            name = (item.findtext("corp_name") or "").strip()
            stock = (item.findtext("stock_code") or "").strip()
            code = (item.findtext("corp_code") or "").strip()
            if q == stock or q == name:
                match = (code, name, stock or None)
                break
            if match is None and q and q in name:
                match = (code, name, stock or None)
        if not match:
            return None
        ksic = self._company_ksic(match[0])
        return CompanyIdentity(match[0], match[1], match[2], ksic)

    def _company_ksic(self, corp_code: str) -> str | None:
        resp = self._get("company.json", corp_code=corp_code)
        data = resp.json()
        if data.get("status") != "000":
            return None
        return data.get("induty_code")

    # ── 회사 데이터 수집 ────────────────────────────────────────────────────────
    def fetch_company(self, corp_code: str, fiscal_year: int, years: int = 5) -> CompanyRecord:
        identity = None
        ksic = self._company_ksic(corp_code)
        name_resp = self._get("company.json", corp_code=corp_code).json()
        corp_name = name_resp.get("corp_name", corp_code)
        stock_code = (name_resp.get("stock_code") or "").strip() or None

        rec = CompanyRecord(
            corp_code=corp_code, corp_name=corp_name, stock_code=stock_code, ksic_code=ksic
        )
        year_range = list(range(fiscal_year - years + 1, fiscal_year + 1))

        rec.disclosures = self._fetch_disclosures(corp_code, year_range[0], fiscal_year)
        for y in year_range:
            fin = self._fetch_financials(corp_code, y)
            if fin:
                rec.financials.append(fin)
            aud = self._fetch_audit(corp_code, y)
            if aud:
                rec.audits.append(aud)

        # 감사인 변경 이력·KAM 등 비정형 파싱은 별도 파서 필요 → 미구현분 기록
        rec.parse_issues.append(
            ("warning", "auditor_change_history",
             "감사인 변경 이력·전기 KAM 상세는 감사보고서 원문 파싱 필요(별도 파서). 수동확인 권장")
        )
        return rec

    def _fetch_disclosures(self, corp_code: str, y0: int, y1: int) -> list[DisclosureRecord]:
        # list.json 응답에는 pblntf_ty 필드가 없다 → 유형별 요청 파라미터로 분리 수집·태깅.
        out: list[DisclosureRecord] = []
        for ty in ("A", "B", "E", "F", "I"):
            resp = self._get(
                "list.json", corp_code=corp_code, bgn_de=f"{y0}0101", end_de=f"{y1}1231",
                pblntf_ty=ty, page_count=100,
            ).json()
            if resp.get("status") != "000":
                continue
            for it in resp.get("list", []):
                nm = it.get("report_nm", "")
                out.append(DisclosureRecord(
                    rcept_no=it["rcept_no"], report_nm=nm, pblntf_ty=ty,
                    rcept_dt=it.get("rcept_dt", ""),
                    corrected="[기재정정]" in nm or "[첨부정정]" in nm,
                    body="",  # 원문 본문은 document.xml 별도 수집(대용량 → 필요 시)
                ))
        return out

    def _fetch_financials(self, corp_code: str, year: int) -> FinancialRecord | None:
        resp = self._get(
            "fnlttSinglAcntAll.json",
            corp_code=corp_code,
            bsns_year=str(year),
            reprt_code=_REPRT_ANNUAL,
            fs_div="CFS",
        ).json()
        if resp.get("status") != "000":
            return None
        fin = FinancialRecord(year=year, basis="CFS")
        for row in resp.get("list", []):
            field = _ACCOUNT_MAP.get((row.get("account_nm") or "").replace(" ", ""))
            if field and getattr(fin, field) is None:
                setattr(fin, field, _num(row.get("thstrm_amount")))
        return fin

    def _fetch_audit(self, corp_code: str, year: int) -> AuditRecord | None:
        resp = self._get(
            "accnutAdtorNmNdAdtOpinion.json",
            corp_code=corp_code,
            bsns_year=str(year),
            reprt_code=_REPRT_ANNUAL,
        ).json()
        if resp.get("status") != "000" or not resp.get("list"):
            return None
        row = resp["list"][0]
        opinion_raw = row.get("adt_opinion", "적정")
        opinion = next((o for o in ("적정", "한정", "부적정", "의견거절") if o in opinion_raw), "적정")
        aud = AuditRecord(
            fiscal_year=year,
            auditor=row.get("adtor", ""),
            opinion=opinion,
        )
        self._augment_fees(aud, corp_code, year)
        return aud

    @staticmethod
    def _fee_num(s) -> float | None:
        # 보수 필드는 이미 백만원 단위 → 콤마만 제거(원 단위 _num과 달리 나누지 않음).
        if not s:
            return None
        s = str(s).replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    def _augment_fees(self, aud: AuditRecord, corp_code: str, year: int) -> None:
        try:
            adt = self._get(
                "adtServcCnclsSttus.json",
                corp_code=corp_code, bsns_year=str(year), reprt_code=_REPRT_ANNUAL,
            ).json()
            if adt.get("status") == "000" and adt.get("list"):
                row = adt["list"][-1]  # 당기 계약
                aud.audit_fee = (self._fee_num(row.get("adt_cntrct_dtls_mendng"))
                                 or self._fee_num(row.get("real_exc_dtls_mendng"))
                                 or self._fee_num(row.get("mendng")))
            non = self._get(
                "acntAdtorNonAdtServcCnclsSttus.json",
                corp_code=corp_code, bsns_year=str(year), reprt_code=_REPRT_ANNUAL,
            ).json()
            if non.get("status") == "000" and non.get("list"):
                total = sum(self._fee_num(r.get("cntrct_amount")) or 0 for r in non["list"])
                aud.non_audit_fee = total or None
        except (httpx.HTTPError, KeyError, ValueError):
            pass
