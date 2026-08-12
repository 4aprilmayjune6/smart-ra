"""정적 쇼케이스 사이트 빌드 — output/ 산출물을 web/ 로 정규화·복사하고 랜딩을 생성한다.

아티팩트용 HTML은 <title>/<style> 로 시작하는 head 조각 + body 로 되어 있어,
독립 정적 서빙을 위해 <!doctype>·<html lang=ko>·<meta charset=utf-8> 로 감싼다.
비밀정보(DART 키)가 산출물에 없음을 빌드 시 재확인한다.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
WEB = ROOT / "web"

# 절대 커밋·배포되면 안 되는 문자열(방어적 재확인). 실제 키 값은 코드에 두지 않는다.
FORBIDDEN_ENV = "SMARTRA_DART_API_KEY"

# 쇼케이스에 실을 산출물 (원본 → 배포명, 카드 메타)
DELIVERABLES = [
    dict(src="memo_amore_2025.html", dst="memo-amore-2025.html", group="real",
         title="아모레퍼시픽 · FY2025", tag="실데이터 + 외부신호",
         desc="OpenDART 실데이터(사업보고서 2026-03) 기반 위험평가 메모. 핵심위험 3건·외부 공개정보 7건. PDF 제공.",
         pdf="memo-amore-2025.pdf", featured=True),
    dict(src="memo_samsung.html", dst="memo-samsung.html", group="real",
         title="삼성전자 · FY2024", tag="실데이터 + 외부신호",
         desc="대형 제조업 실데이터 메모. 공시·산업·재무 신호 교차검증 + 감리 선례 편입."),
    dict(src="memo_daeyang.html", dst="memo-daeyang.html", group="sample",
         title="대양제조 · 샘플", tag="건전 제조",
         desc="fixture 샘플 — 계속기업 GREEN(재무 양호) 사례."),
    dict(src="memo_hanbit.html", dst="memo-hanbit.html", group="sample",
         title="한빛건설 · 샘플", tag="부실 · 하드룰 RED",
         desc="fixture 샘플 — 계속기업 하드룰 발동으로 즉시 적색 판정."),
    dict(src="memo_geno.html", dst="memo-geno.html", group="sample",
         title="제노바이오 · 샘플", tag="수익 전 바이오 · YELLOW",
         desc="fixture 샘플 — 현금 runway 기반 계속기업 불확실성(YELLOW)."),
    dict(src="dashboard.html", dst="dashboard.html", group="tool",
         title="위험평가 대시보드", tag="다회사 비교",
         desc="회사별 신호등·계속기업 점수·핵심위험을 한눈에 비교하는 대시보드."),
    dict(src="RFP_rendered.html", dst="rfp.html", group="doc",
         title="제안요청서(RFP) 전문", tag="v1.3",
         desc="SMART-RA 제안요청서 전문. IR-07 외부정보 소스 등 신규 요구사항 상단 요약."),
]

EXTRA_COPY = ["memo_amore_2025.pdf"]  # PDF 등 바이너리 그대로 복사(배포명 유지 매핑 아래)
PDF_RENAME = {"memo_amore_2025.pdf": "memo-amore-2025.pdf"}


def wrap_document(raw: str) -> str:
    """head 조각(<title>…</style>) + body 를 완전한 HTML5 문서로 감싼다."""
    s = raw.lstrip().lower()
    if s.startswith("<!doctype") or s.startswith("<html"):
        return raw  # 이미 완전한 문서
    styles = list(re.finditer(r"</style\s*>", raw, re.I))
    idx = styles[-1].end() if styles else 0
    head, body = raw[:idx], raw[idx:]
    return (
        "<!doctype html>\n<html lang=\"ko\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"{head.strip()}\n</head>\n<body>\n{body.strip()}\n</body>\n</html>\n"
    )


def assert_clean(text: str, where: str) -> None:
    if FORBIDDEN_ENV in text and "os.environ" not in text:
        # 산출물에 환경변수 이름이 섞여도 값이 아니면 허용하되, 40자 hex 키 패턴은 차단
        pass
    if re.search(r"\b[0-9a-f]{40}\b", text) and where.endswith((".html", ".pdf")):
        # 40자 hex(스냅샷 해시는 12~16자라 오탐 낮음) → 경고성 차단
        raise SystemExit(f"[중단] {where} 에 40자 hex 문자열 발견 — 키 유출 의심. 확인 필요.")


def main() -> None:
    if WEB.exists():
        shutil.rmtree(WEB)
    WEB.mkdir(parents=True)

    cards = []
    for d in DELIVERABLES:
        src = OUT / d["src"]
        if not src.exists():
            print(f"  (건너뜀, 없음) {d['src']}")
            continue
        raw = src.read_text(encoding="utf-8")
        assert_clean(raw, d["dst"])
        (WEB / d["dst"]).write_text(wrap_document(raw), encoding="utf-8")
        cards.append(d)
        print(f"  wrap  {d['src']:26s} → web/{d['dst']}")

    for name in EXTRA_COPY:
        src = OUT / name
        if src.exists():
            dst = PDF_RENAME.get(name, name)
            data = src.read_bytes()
            # PDF 텍스트에 키가 없음은 생성 단계에서 이미 assert했으나 방어적 재확인
            if b"SMARTRA_DART_API_KEY" in data:
                raise SystemExit(f"[중단] {name} 에 키 환경변수명 포함")
            (WEB / dst).write_bytes(data)
            print(f"  copy  {name:26s} → web/{dst}")

    # index.html 은 실시간 검색 UI(api/analyze)를 손으로 유지한다. 이미 검색 폼이
    # 들어 있으면 덮어쓰지 않는다(정적 재빌드가 동적 기능을 지우지 않도록).
    index_path = WEB / "index.html"
    if index_path.exists() and 'id="analyzeForm"' in index_path.read_text(encoding="utf-8"):
        print("  index web/index.html — 검색 UI 유지(재생성 건너뜀)")
    else:
        index_path.write_text(render_index(cards), encoding="utf-8")
        print(f"  index web/index.html ({len(cards)} 카드)")
    # 노-크롤 보조
    (WEB / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    print("완료 → web/")


def render_index(cards: list[dict]) -> str:
    groups = [
        ("real", "실데이터 메모", "OpenDART 실공시 기반 · 외부 공개정보(기사·감리선례) 편입"),
        ("sample", "샘플 메모", "인증키 없이 재현되는 fixture 3사"),
        ("tool", "대시보드", "다회사 위험 비교"),
        ("doc", "제안요청서", "요구사항 명세 전문"),
    ]
    def card_html(d: dict) -> str:
        pdf = (f'<a class="pdf" href="{d["pdf"]}" download>PDF ↓</a>' if d.get("pdf") else "")
        feat = " featured" if d.get("featured") else ""
        return f'''<a class="card{feat}" href="{d['dst']}">
        <div class="ctag">{d['tag']}</div>
        <h3>{d['title']}</h3>
        <p>{d['desc']}</p>
        <div class="cfoot"><span class="open">열기 →</span>{pdf}</div>
      </a>'''
    sections = []
    for gid, gtitle, gsub in groups:
        gc = [c for c in cards if c["group"] == gid]
        if not gc:
            continue
        sections.append(
            f'''<section>
      <div class="sec-h"><h2>{gtitle}</h2><span>{gsub}</span></div>
      <div class="grid">{''.join(card_html(c) for c in gc)}</div>
    </section>''')
    body = "\n".join(sections)
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMART-RA · 감사 위험평가 산출물</title>
<meta name="description" content="DART 공시 기반 감사 위험평가 자동화(SMART-RA) 참조구현 산출물 — 위험평가 메모·대시보드·제안요청서.">
<style>
  :root {{
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
    --sans:system-ui,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",Pretendard,sans-serif;
    --mono:ui-monospace,"Cascadia Code",Consolas,Menlo,monospace;
    --paper:#eef1f6; --sheet:#fff; --ink:#191d26; --muted:#56606f; --faint:#8b94a2;
    --rule:#dde2ea; --rule-strong:#c6cedb; --accent:#1f3a5f; --accent-soft:#e9eef6;
  }}
  @media (prefers-color-scheme:dark){{:root{{
    --paper:#0a0d12; --sheet:#14181f; --ink:#e7ebf2; --muted:#99a3b1; --faint:#69717f;
    --rule:#232a36; --rule-strong:#333c4b; --accent:#88adde; --accent-soft:#182541;
  }}}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.6;
    -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:1040px;margin:0 auto;padding:56px 24px 80px}}
  header{{border-bottom:2px solid var(--accent);padding-bottom:22px;margin-bottom:8px}}
  .kicker{{font-size:.7rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:var(--faint)}}
  h1{{font-family:var(--serif);font-size:2.5rem;line-height:1.1;font-weight:600;margin:.35em 0 .15em;
    letter-spacing:-.01em}}
  .lead{{color:var(--muted);font-size:1.05rem;max-width:60ch}}
  .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}}
  .badge{{font-family:var(--mono);font-size:.72rem;color:var(--muted);background:var(--accent-soft);
    border:1px solid var(--rule-strong);border-radius:999px;padding:4px 11px}}
  section{{margin-top:44px}}
  .sec-h{{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--rule-strong);
    padding-bottom:8px;margin-bottom:18px;flex-wrap:wrap}}
  .sec-h h2{{font-size:1.15rem;margin:0;font-weight:700}}
  .sec-h span{{color:var(--faint);font-size:.82rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:16px}}
  .card{{display:flex;flex-direction:column;gap:8px;text-decoration:none;color:inherit;
    background:var(--sheet);border:1px solid var(--rule);border-radius:12px;padding:18px 20px;
    transition:border-color .15s, transform .15s, box-shadow .15s}}
  .card:hover{{border-color:var(--accent);transform:translateY(-2px);
    box-shadow:0 10px 30px rgba(20,30,50,.10)}}
  .card.featured{{border-left:5px solid var(--accent);background:var(--accent-soft)}}
  .ctag{{font-size:.66rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}}
  .card h3{{font-family:var(--serif);font-size:1.24rem;font-weight:700;margin:0}}
  .card p{{margin:0;color:var(--muted);font-size:.88rem;flex:1}}
  .cfoot{{display:flex;align-items:center;justify-content:space-between;margin-top:6px}}
  .open{{font-size:.82rem;font-weight:700;color:var(--accent)}}
  .pdf{{font-family:var(--mono);font-size:.72rem;font-weight:700;color:var(--muted);
    border:1px solid var(--rule-strong);border-radius:6px;padding:3px 9px;text-decoration:none}}
  .pdf:hover{{border-color:var(--accent);color:var(--accent)}}
  footer{{margin-top:56px;padding-top:20px;border-top:1px solid var(--rule);color:var(--faint);
    font-size:.8rem;line-height:1.7}}
  footer code{{font-family:var(--mono);color:var(--muted)}}
  a.src{{color:var(--accent);text-decoration:none;border-bottom:1px dotted var(--accent)}}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="kicker">DART · 감사 위험평가 자동화 (참조구현)</div>
      <h1>SMART-RA 산출물</h1>
      <p class="lead">한국 회계법인 감사계획용 위험평가 자동화 플랫폼의 참조구현 산출물입니다.
      판정은 서버측 <strong>결정론 룰·산식</strong>으로, 서술은 근거 인용 기반으로 생성됩니다.</p>
      <div class="badges">
        <span class="badge">KSA 315·240·570</span>
        <span class="badge">K-IFRS 1115·1036·1002</span>
        <span class="badge">MCP 서버(16종 도구)</span>
        <span class="badge">결정론 · 재현가능</span>
        <span class="badge">자동생성 초안(SFR-405)</span>
      </div>
    </header>
    {body}
    <footer>
      본 산출물은 시스템이 자동 생성한 <strong>초안(draft)</strong>이며 감사인의 전문가적 판단을 대체하지 않습니다.
      최종 위험평가·유의적 위험 결정·감사절차 결정은 업무수행이사와 감사팀이 수행합니다(감사기준서 500·SFR-405).<br>
      산업 위험맵·교차검증 룰의 감사 콘텐츠는 참조용 초안으로, 실제 사용 전 회계사(SME) 검수가 필요합니다.<br>
      소스코드 · MCP 서버: <a class="src" href="https://github.com/4aprilmayjune6/smart-ra">GitHub 저장소</a> · 룰 <code>risk-rules@0.1.0</code>
    </footer>
  </div>
</body>
</html>
'''


if __name__ == "__main__":
    main()
