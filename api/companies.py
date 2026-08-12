"""회사 자동완성 목록 API — 프론트 검색창 datalist용.

rest 모드: 상장사(종목코드 보유) 전체(공개정보). fixture 모드: 샘플 3사.
프로세스 캐시(corpCode.xml) 덕분에 웜 인스턴스에서는 즉시 응답한다.
"""
from __future__ import annotations

import json
import pathlib
import sys
import traceback
from http.server import BaseHTTPRequestHandler

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _companies() -> list[dict]:
    from smart_ra.dart import get_adapter

    adapter = get_adapter()
    if getattr(adapter, "source", "") == "rest":
        return adapter.listed_companies()
    # fixture
    return [
        {"name": ci.corp_name, "stock": ci.stock_code or "", "corp": ci.corp_code}
        for ci in adapter.available()
    ]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (Vercel 규약)
        try:
            payload = {"companies": _companies()}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # 목록은 하루 단위로 안정적 → CDN 캐시 허용(1시간)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            err = json.dumps(
                {"companies": [], "error": traceback.format_exc()[-500:]},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
