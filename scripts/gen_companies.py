"""상장사 목록(web/companies.json) 생성 — 프론트 검색 자동완성용.

corpCode.xml(약 3.6MB)은 Vercel 서버리스에선 대역폭 제약으로 런타임 다운로드가 불가하다.
그래서 이 스크립트로 **로컬(국내 IP)** 에서 한 번 받아 상장사(종목코드 보유) 목록을
정적 파일로 만든다. 회사명·종목코드·corp_code 는 모두 공개정보다.

사용법(회원님 터미널에서, 키는 로컬 환경변수로만):
    PowerShell:  $env:SMARTRA_DART_API_KEY="<재발급한 키>"
                 .venv\\Scripts\\python scripts\\gen_companies.py
    Bash:        SMARTRA_DART_API_KEY=<키> .venv/Scripts/python scripts/gen_companies.py

키는 파일·출력에 절대 기록하지 않는다(생성 후 자체 검증).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from smart_ra.config import settings
from smart_ra.dart.rest_client import RestDartAdapter

OUT = Path(__file__).resolve().parent.parent / "web" / "companies.json"


def main() -> None:
    if not settings.dart_api_key:
        sys.exit("SMARTRA_DART_API_KEY 환경변수가 필요합니다(로컬에서만 설정).")

    adapter = RestDartAdapter()
    print("corpCode.xml 다운로드·파싱 중… (수십 초 소요될 수 있음)")
    companies = adapter.listed_companies()
    companies.sort(key=lambda c: c["name"])

    payload = {"count": len(companies), "companies": companies}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    # 키 유출 방지 — 산출물에 인증키가 없는지 확인
    if settings.dart_api_key in text:
        sys.exit("[중단] 산출물에 인증키가 포함됨")

    OUT.write_text(text, encoding="utf-8")
    print(f"완료 → {OUT}  (상장사 {len(companies):,}개)")


if __name__ == "__main__":
    main()
