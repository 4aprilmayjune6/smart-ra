"""설정 — DART 인증키 등 시크릿은 환경변수/시크릿 저장소에서 주입한다(NFR-SEC-04).

코드·로그에 키를 하드코딩하지 않는다. 키가 없으면 fixture(샘플 데이터) 모드로 동작하여
DART 인증키 없이도 전체 파이프라인이 재현 가능하다(참조구현 목적).
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
RULES_DIR = PACKAGE_DIR / "rules"
FIXTURES_DIR = PACKAGE_DIR / "fixtures"
TEMPLATES_DIR = PACKAGE_DIR / "memo" / "templates"


class Settings(BaseSettings):
    """환경변수 기반 설정. 접두사 SMARTRA_ 사용. 예: SMARTRA_DART_API_KEY."""

    model_config = SettingsConfigDict(env_prefix="SMARTRA_", env_file=".env", extra="ignore")

    # DART 인증키. 미설정 시 fixture 모드로 자동 전환(dart_source="fixture").
    dart_api_key: str | None = None
    # "auto" | "fixture" | "rest"
    dart_source: str = "auto"
    # OpenDART API 베이스 URL (IR-01). 사양 변경 대비 설정화.
    dart_base_url: str = "https://opendart.fss.or.kr/api"
    # 일일 쿼터(현행 20,000건 수준, IR-01) — 스로틀 참고값.
    dart_daily_quota: int = 20000

    # SQLite 저장소 경로. ":memory:" 이면 인메모리.
    db_path: str = ":memory:"

    def effective_dart_source(self) -> str:
        if self.dart_source == "auto":
            return "rest" if self.dart_api_key else "fixture"
        return self.dart_source


settings = Settings()
