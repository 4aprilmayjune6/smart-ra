"""동적 위험평가 API — 회사명·연도 → 실시간 DART 수집·분석 → 메모 HTML.

Vercel Python 서버리스 함수. 프론트(web/index.html)의 검색 폼이 호출한다.
인증키(SMARTRA_DART_API_KEY)가 Vercel 환경변수로 설정되면 실제 상장사를,
미설정 시 fixture 샘플 3사(한빛건설·대양제조·제노바이오)를 분석한다.

키는 서버 환경변수로만 사용하며 응답·로그·코드에 노출하지 않는다(NFR-SEC-04).
"""
from __future__ import annotations

import datetime
import pathlib
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote_to_bytes, urlparse

# 번들에 포함된 smart_ra 패키지를 임포트 경로에 추가(vercel.json includeFiles).
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ACCENT = "#1f3a5f"
_YEAR_MIN, _YEAR_MAX = 2015, 2025


def _decode_param(query: str, key: str) -> str:
    """퍼센트 인코딩된 쿼리에서 key 값을 raw 바이트로 언쿼트 후 인코딩 자동판별.

    브라우저(fetch)는 UTF-8, 일부 클라이언트(cp949 셸의 curl 등)는 EUC-KR로 인코딩한다.
    parse_qs의 UTF-8 강제 디코딩은 cp949 바이트를 손실(U+FFFD)시키므로 직접 처리한다.
    """
    for pair in query.split("&"):
        k, _, v = pair.partition("=")
        if k != key:
            continue
        raw = unquote_to_bytes(v.replace("+", " "))
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")
    return ""


def _now_kst() -> str:
    kst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")


def _wrap(raw: str) -> str:
    """메모 템플릿 출력(<title>…<style>…본문)을 완전한 HTML 문서로 감싼다."""
    s = raw.lstrip().lower()
    if s.startswith("<!doctype") or s.startswith("<html"):
        return raw
    styles = list(re.finditer(r"</style\s*>", raw, re.I))
    idx = styles[-1].end() if styles else 0
    head, body = raw[:idx], raw[idx:]
    return (
        '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head.strip()}\n</head>\n<body>\n{body.strip()}\n</body>\n</html>\n"
    )


def _error_page(title: str, detail: str, hint: str = "") -> str:
    from html import escape

    hint_html = f'<p class="hint">{escape(hint)}</p>' if hint else ""
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<style>
  :root{{--ink:#191d26;--muted:#56606f;--paper:#eef1f6;--sheet:#fff;--rule:#dde2ea;--accent:{_ACCENT}}}
  @media (prefers-color-scheme:dark){{:root{{--ink:#e7ebf2;--muted:#99a3b1;--paper:#0a0d12;--sheet:#14181f;--rule:#232a36;--accent:#88adde}}}}
  html,body{{margin:0;background:var(--paper);color:var(--ink);
    font-family:system-ui,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;line-height:1.6}}
  .box{{max-width:560px;margin:12vh auto;padding:32px 28px;background:var(--sheet);
    border:1px solid var(--rule);border-left:5px solid var(--accent);border-radius:12px}}
  h1{{font-size:1.2rem;margin:0 0 10px}} p{{color:var(--muted);margin:.4em 0}}
  .detail{{font-family:ui-monospace,Consolas,monospace;font-size:.86rem;color:var(--ink);
    background:var(--paper);border:1px solid var(--rule);border-radius:8px;padding:10px 12px;
    white-space:pre-wrap;word-break:break-word}}
  .hint{{font-size:.9rem}}
</style></head><body><div class="box">
  <h1>⚠ {escape(title)}</h1>
  <div class="detail">{escape(detail)}</div>
  {hint_html}
</div></body></html>"""


def analyze(name: str, year: int, corp: str = "") -> tuple[int, str]:
    """분석 실행 → (status, html). 실패는 사용자용 에러 페이지로 반환.

    corp(8자리 corp_code)가 주어지면 회사식별을 건너뛰고 바로 분석한다(권장, 빠름).
    없으면 name 으로 resolve 하는데, 이때 대용량 corpCode.xml 다운로드가 필요해 느리다.
    """
    from smart_ra.dart.schema import CompanyRecord
    from smart_ra.memo.html_generator import generate_memo_html
    from smart_ra.service import EngagementNotFound, SmartRaService

    svc = SmartRaService()
    try:
        if corp:
            engagement, job = svc.register_by_corp_code(
                corp, year, corp_name=name or None, years=3)
        else:
            engagement, job = svc.register_engagement(name, year)
    except EngagementNotFound:
        return 404, _error_page(
            "회사를 찾지 못했습니다",
            f"'{name or corp}' (FY{year})",
            "검색창의 자동완성 목록에서 회사를 선택해 주세요.",
        )

    from smart_ra.models import JobStatus

    if job.status == JobStatus.FAILED:
        return 502, _error_page(
            "데이터 수집 실패",
            job.message or "OpenDART 수집 중 오류",
            "일시적 오류이거나 해당 연도 사업보고서가 아직 없을 수 있습니다. "
            "다른 연도로 다시 시도해 보세요.",
        )

    # 네이버 뉴스 자동 편입 — NAVER_CLIENT_ID/SECRET 있을 때만. 외부 비신뢰 신호로 태깅되며
    # 판정 자동확정 없이 YELLOW 상한(SFR-606). 자격증명 없거나 실패 시 조용히 건너뛴다.
    try:
        from smart_ra.external.naver_news import fetch_news
        search_name = (name or engagement.corp_name or "").replace("(주)", "").replace("주식회사", "").strip()
        hits = fetch_news(search_name) if search_name else []
        if hits:
            svc.ingest_external(engagement.engagement_id, news=hits)
    except Exception:  # noqa: BLE001 — 뉴스는 부가정보(메모 생성에 영향 없음)
        pass

    record = CompanyRecord.model_validate(svc.repo.get_snapshot(engagement.snapshot_id or ""))
    signals = svc.repo.list_signals(engagement.engagement_id)
    assessment = svc.repo.get_assessment(engagement.engagement_id)
    cross = svc.run_cross_validation(engagement.engagement_id)
    svc.repo.save_key_risks(engagement.engagement_id, cross.key_risks)
    html = generate_memo_html(
        engagement, record, signals, assessment, cross, generated_at=_now_kst()
    )
    return 200, _wrap(html)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (Vercel 규약)
        try:
            query = urlparse(self.path).query
            name = (_decode_param(query, "q") or _decode_param(query, "name")).strip()[:80]
            year_raw = _decode_param(query, "year").strip()
            corp = "".join(ch for ch in _decode_param(query, "corp") if ch.isdigit())[:8]

            if not name and not corp:
                return self._send(400, _error_page(
                    "회사가 필요합니다", "q(회사명) 또는 corp(corp_code) 파라미터가 비어 있습니다."))
            try:
                year = int(year_raw)
            except ValueError:
                return self._send(400, _error_page(
                    "연도가 올바르지 않습니다", f"year='{year_raw}'"))
            if not (_YEAR_MIN <= year <= _YEAR_MAX):
                return self._send(400, _error_page(
                    "지원 범위를 벗어난 연도",
                    f"year={year}",
                    f"{_YEAR_MIN}~{_YEAR_MAX} 사이의 사업연도를 선택하세요."))

            status, html = analyze(name, year, corp=corp)
            return self._send(status, html)
        except Exception:  # noqa: BLE001 — 예기치 못한 오류도 페이지로 표면화
            return self._send(500, _error_page(
                "분석 중 오류가 발생했습니다",
                traceback.format_exc()[-1500:],
                "잠시 후 다시 시도해 주세요."))

    def _send(self, status: int, html_text: str) -> None:
        data = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
