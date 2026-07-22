"""CLI — 비-LLM 동등 경로(SFR-607). 파이프라인 검증·데모용."""
from __future__ import annotations

import argparse
import sys

from .dart.fixture_client import FixtureDartAdapter
from .service import SmartRaService


def _print_analysis(svc: SmartRaService, query: str, year: int, show_memo: bool) -> None:
    engagement, job = svc.register_engagement(query, year)
    print(f"\n=== {engagement.corp_name} ({engagement.fiscal_year}) · {engagement.engagement_id} ===")
    print(f"수집 job: {job.status.value} · {job.message} · 스냅샷 {engagement.snapshot_id}")

    gc = svc.get_going_concern(engagement.engagement_id)
    print(f"[모듈3] 계속기업: {gc.overall_severity.emoji} {gc.overall_severity.value} "
          f"(점수 {gc.overall_score})" + (f" · 하드룰: {gc.hard_rule_triggered}" if gc.hard_rule_triggered else ""))

    print("[모듈1/2] 신호:")
    for s in svc.get_signals(engagement.engagement_id):
        if s.severity.value == "GREEN":
            continue
        ev = f" · {s.evidence[0].rcept_no}" if s.evidence and s.evidence[0].rcept_no else ""
        print(f"  {s.severity.emoji} [{s.module}.{s.category}] {s.title}{ev}")

    cross = svc.run_cross_validation(engagement.engagement_id)
    print(f"[모듈4] 핵심위험 {len(cross.key_risks)}건:")
    for kr in cross.key_risks:
        flag = " ★유의적위험후보" if kr.significant_risk_candidate else ""
        print(f"  · ({kr.rule_id}) {kr.title}{flag}")

    if show_memo:
        memo = svc.generate_memo_draft(engagement.engagement_id)
        print(f"\n----- 메모 초안 {memo.memo_id} (v{memo.version}) -----\n")
        print(memo.body_markdown)


def main(argv: list[str] | None = None) -> int:
    try:  # Windows 콘솔(cp949)에서 이모지·한글 출력 보장
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(prog="smart-ra", description="SMART-RA 참조구현 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("companies", help="fixture 회사 목록")
    p_an = sub.add_parser("analyze", help="회사 분석(등록→수집→모듈1~4)")
    p_an.add_argument("query", help="법인명 또는 종목코드 또는 corp_code")
    p_an.add_argument("--year", type=int, default=2024)
    p_an.add_argument("--memo", action="store_true", help="메모 초안 전문 출력")
    sub.add_parser("demo", help="fixture 전체 요약 실행")

    args = parser.parse_args(argv)
    svc = SmartRaService()

    if args.cmd == "companies":
        for c in FixtureDartAdapter.available():
            print(f"{c.corp_code}  {c.corp_name}  (종목 {c.stock_code}, KSIC {c.ksic_code})")
        return 0
    if args.cmd == "analyze":
        _print_analysis(svc, args.query, args.year, args.memo)
        return 0
    if args.cmd == "demo":
        for c in FixtureDartAdapter.available():
            _print_analysis(SmartRaService(), c.corp_code, 2024, show_memo=False)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
