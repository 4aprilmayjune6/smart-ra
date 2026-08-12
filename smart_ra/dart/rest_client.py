"""OpenDART REST 어댑터 — 공식 API 사양 기반(IR-01).

인증키(SMARTRA_DART_API_KEY)가 설정된 경우 활성화된다. 구조화 엔드포인트
(재무제표·감사의견·보수)를 우선 사용하고, 비정형 감사보고서 원문 파싱이 필요한
항목(감사인 변경 이력 등)은 best-effort로 처리하며 실패 시 parse_issues에 기록한다(SFR-C07).

주의: 정확한 엔드포인트·필드는 구현 착수 시점의 OpenDART 개발가이드 최신본으로
확정하고 계약 테스트(contract test)로 고정해야 한다(NFR-MNT-03).
"""
from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html import unescape

from ..config import settings
from .adapter import CompanyIdentity
from .schema import AuditRecord, CompanyRecord, DisclosureRecord, FinancialRecord

_REPRT_ANNUAL = "11011"  # 사업보고서

# corpCode.xml(약 1MB zip) 파싱 결과 프로세스 캐시 — (corp_name, stock_code, corp_code).
# 서버리스 웜 인스턴스에서 재다운로드·재파싱을 피한다(SFR-C02: 실운영은 일 1회 갱신).
_CORP_LIST_CACHE: list[tuple[str, str, str]] | None = None

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
        self._timeout = 30.0

    # HTTP 계층은 표준 라이브러리(urllib)를 쓴다. httpx 는 일부 서버리스 런타임(Vercel)에서
    # 요청이 멈추는 문제가 있어 의존성 없이 안정적인 urllib 로 대체한다.
    def _fetch(self, endpoint: str, params: dict) -> bytes:
        params = dict(params)
        params["crtfc_key"] = self._key
        url = f"{self._base}/{endpoint}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "smart-ra/0.1"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return resp.read()

    def _get_json(self, endpoint: str, **params) -> dict:
        try:
            return json.loads(self._fetch(endpoint, params).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {"status": "999", "message": "invalid response"}

    # ── 회사 식별 ─────────────────────────────────────────────────────────────
    def _corp_list(self) -> list[tuple[str, str, str]]:
        """corpCode.xml 을 (corp_name, stock_code, corp_code) 목록으로 파싱(프로세스 캐시).

        약 10만 건이라 ElementTree 는 제약된 서버리스 CPU에서 수십 초가 걸린다.
        레코드 순서(corp_code→corp_name→…→stock_code)가 안정적이므로 정규식으로 일괄 추출한다.
        """
        global _CORP_LIST_CACHE
        if _CORP_LIST_CACHE is not None:
            return _CORP_LIST_CACHE
        content = self._fetch("corpCode.xml", {})
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            text = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
        pattern = re.compile(
            r"<corp_code>\s*(.*?)\s*</corp_code>.*?"
            r"<corp_name>\s*(.*?)\s*</corp_name>.*?"
            r"<stock_code>\s*(.*?)\s*</stock_code>",
            re.S,
        )
        out: list[tuple[str, str, str]] = []
        for code, name, stock in pattern.findall(text):
            name = unescape(name).strip()
            code = code.strip()
            stock = stock.strip()
            if name and code:
                out.append((name, stock, code))
        _CORP_LIST_CACHE = out
        return out

    def listed_companies(self) -> list[dict]:
        """상장사(종목코드 보유) 목록 — 프론트 자동완성용. 공개정보."""
        return [
            {"name": name, "stock": stock, "corp": code}
            for (name, stock, code) in self._corp_list()
            if stock
        ]

    def resolve_corp(self, query: str) -> CompanyIdentity | None:
        q = query.strip()
        match = None
        for (name, stock, code) in self._corp_list():
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
        data = self._get_json("company.json", corp_code=corp_code)
        if data.get("status") != "000":
            return None
        return data.get("induty_code")

    # ── 회사 데이터 수집 ────────────────────────────────────────────────────────
    def fetch_company(self, corp_code: str, fiscal_year: int, years: int = 5,
                      include_fees: bool = True) -> CompanyRecord:
        # include_fees=False 면 감사보수 조회(연 2회 호출)를 생략한다 — 서버리스 응답시간 단축용.
        # 독립적인 DART 호출(공시목록·연도별 재무·감사)을 스레드풀로 병렬 수집한다. urllib 는
        # 소켓 I/O 중 GIL 을 해제하므로 총 소요가 합계 대신 최대치에 수렴한다(서버리스 60초 제약 대응).
        info = self._get_json("company.json", corp_code=corp_code)  # 회사개황 1회로 명칭·업종·종목
        ok = info.get("status") == "000"
        corp_name = (info.get("corp_name") if ok else None) or corp_code
        stock_code = (info.get("stock_code") or "").strip() or None
        ksic = info.get("induty_code") if ok else None

        rec = CompanyRecord(
            corp_code=corp_code, corp_name=corp_name, stock_code=stock_code, ksic_code=ksic
        )
        year_range = list(range(fiscal_year - years + 1, fiscal_year + 1))

        with ThreadPoolExecutor(max_workers=8) as ex:
            disc_futs = [
                ex.submit(self._fetch_disclosure_type, corp_code, year_range[0], fiscal_year, ty)
                for ty in ("A", "B", "E", "F", "I")
            ]
            fin_futs = {y: ex.submit(self._fetch_financials, corp_code, y) for y in year_range}
            aud_futs = {y: ex.submit(self._fetch_audit, corp_code, y, include_fees)
                        for y in year_range}
            for f in disc_futs:
                rec.disclosures.extend(f.result())
            for y in year_range:
                fin = fin_futs[y].result()
                if fin:
                    rec.financials.append(fin)
                aud = aud_futs[y].result()
                if aud:
                    rec.audits.append(aud)

        # 감사인 변경 이력·KAM 등 비정형 파싱은 별도 파서 필요 → 미구현분 기록
        rec.parse_issues.append(
            ("warning", "auditor_change_history",
             "감사인 변경 이력·전기 KAM 상세는 감사보고서 원문 파싱 필요(별도 파서). 수동확인 권장")
        )
        return rec

    def _fetch_disclosure_type(self, corp_code: str, y0: int, y1: int, ty: str) -> list[DisclosureRecord]:
        # list.json 응답에는 pblntf_ty 필드가 없다 → 유형별 요청 파라미터로 분리 수집·태깅.
        out: list[DisclosureRecord] = []
        resp = self._get_json(
            "list.json", corp_code=corp_code, bgn_de=f"{y0}0101", end_de=f"{y1}1231",
            pblntf_ty=ty, page_count=100,
        )
        if resp.get("status") != "000":
            return out
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
        resp = self._get_json(
            "fnlttSinglAcntAll.json",
            corp_code=corp_code,
            bsns_year=str(year),
            reprt_code=_REPRT_ANNUAL,
            fs_div="CFS",
        )
        if resp.get("status") != "000":
            return None
        fin = FinancialRecord(year=year, basis="CFS")
        for row in resp.get("list", []):
            field = _ACCOUNT_MAP.get((row.get("account_nm") or "").replace(" ", ""))
            if field and getattr(fin, field) is None:
                setattr(fin, field, _num(row.get("thstrm_amount")))
        return fin

    def _fetch_audit(self, corp_code: str, year: int, include_fees: bool = True) -> AuditRecord | None:
        resp = self._get_json(
            "accnutAdtorNmNdAdtOpinion.json",
            corp_code=corp_code,
            bsns_year=str(year),
            reprt_code=_REPRT_ANNUAL,
        )
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
        if include_fees:
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
            adt = self._get_json(
                "adtServcCnclsSttus.json",
                corp_code=corp_code, bsns_year=str(year), reprt_code=_REPRT_ANNUAL,
            )
            if adt.get("status") == "000" and adt.get("list"):
                row = adt["list"][-1]  # 당기 계약
                aud.audit_fee = (self._fee_num(row.get("adt_cntrct_dtls_mendng"))
                                 or self._fee_num(row.get("real_exc_dtls_mendng"))
                                 or self._fee_num(row.get("mendng")))
            non = self._get_json(
                "acntAdtorNonAdtServcCnclsSttus.json",
                corp_code=corp_code, bsns_year=str(year), reprt_code=_REPRT_ANNUAL,
            )
            if non.get("status") == "000" and non.get("list"):
                total = sum(self._fee_num(r.get("cntrct_amount")) or 0 for r in non["list"])
                aud.non_audit_fee = total or None
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            pass
