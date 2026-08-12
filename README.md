# SMART-RA — DART 공시 기반 감사 위험평가 자동화 플랫폼 (참조구현)

RFP `RFP_v1.0_audit-risk-platform.md`(내부 버전 v1.2, MCP 기반)의 **Phase 0/1 범위 참조구현**이다.
4개 모듈(공시 위험신호·산업 위험매핑·계속기업 스코어링·위험평가 메모)을 **결정론 엔진**으로 구현하고,
**MCP 서버**로 제공한다. DART 인증키 없이도 샘플 데이터(fixture)로 전체 파이프라인이 재현된다.

## 핵심 설계 원칙 (RFP 8.1 / 3.5)

- **판정은 서버, 서술은 에이전트(SFR-602)**: 신호·점수·핵심위험·메모 초안은 전량 서버측 결정론
  룰/산식으로 산출한다. LLM/블랙박스 ML을 판정에 쓰지 않는다.
- **근거 강제(NFR-REL-01)**: 모든 신호는 근거(evidence, rcept_no)를 최소 1개 가진다.
- **재현성(NFR-REL-02)**: 동일 스냅샷·동일 룰 버전 → 동일 산출. ID는 내용 해시 기반.
- **승인은 사람(SFR-604)**: 메모 승인·삭제·JET 직접 조작 MCP 도구는 **존재하지 않는다**.

## 설치 · 실행

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # 또는: pip install pydantic pyyaml jinja2 httpx mcp

# CLI (비-LLM 동등 경로, SFR-607)
.venv/Scripts/python -m smart_ra.cli companies          # 샘플 회사 목록
.venv/Scripts/python -m smart_ra.cli analyze 한빛건설 --year 2024 --memo
.venv/Scripts/python -m smart_ra.cli demo               # 3개사 요약

# 테스트
.venv/Scripts/python -m pytest -q
```

> Windows 콘솔에서 한글/이모지가 깨지면 `PYTHONIOENCODING=utf-8` 을 설정한다(CLI는 stdout을 UTF-8로 자동 재설정).

## MCP 서버

```bash
# stdio 로 기동(개발). 운영은 Streamable HTTP + OAuth 2.1 (IR-06, 미포함)
.venv/Scripts/python -m smart_ra.mcp_server
```

Claude Code에 등록:

```bash
claude mcp add smart-ra -- <절대경로>/.venv/Scripts/python.exe -m smart_ra.mcp_server
```

등록 후 에이전트에서: *"한빛건설 2024년 위험평가 해줘"* → `register_engagement` → `get_risk_signals` →
`get_going_concern_assessment` → `run_cross_validation` → `generate_memo_draft` 순으로 도구가 호출된다.

### 제공 도구 (부록 D — 16종)

| 도구 | 구분 | 모듈 |
|---|---|---|
| list_engagements / register_engagement / refresh_company_data / get_job_status | 공통 | — |
| get_risk_signals / get_signal_evidence / get_disclosure_excerpt | 조회 | M1 |
| ingest_external_findings | 쓰기 | M1·M2 |
| get_industry_risk_profile | 조회 | M2 |
| get_going_concern_assessment | 조회 | M3 |
| run_cross_validation / generate_memo_draft / update_memo_section / submit_memo_for_approval / export_memo / get_jet_update_status | 조회·쓰기 | M4 |

**외부 공개정보 편입**: 에이전트가 WebSearch(기사)·ifrs MCP `search_audit_case`(금감원 감리지적사례)로
수집한 외부 정보를 `ingest_external_findings` 로 주입하면, 서버가 결정론으로 정규화한다. 외부 유래는
`untrusted`(기사)/`trusted`(감리사례)로 태깅하고 **YELLOW 상한**(자동 RED 확정 금지, 수동확인 경유)을
적용한다. 재수집(refresh) 시 주입분은 자동 보존된다.

리소스: `smartra://industry-map/{id}`, `smartra://memo/{id}` · 프롬프트: `risk_assessment_review`
**의도적 비제공**: `approve_memo`(승인은 웹 콘솔 전용), 삭제, JET 직접 조작.

## 아키텍처 / RFP 매핑

```
에이전트(MCP 클라이언트) ─MCP(stdio)→ mcp_server.py  ┐
                                CLI ────────────────┤→ service.py (오케스트레이션, SFR-607)
                                                     ┘        │
   dart/ (수집 어댑터: fixture | OpenDART REST)  ◄────────────┤
   modules/module1_disclosure  (SFR-101~110)                 │
   modules/module2_industry    (SFR-201~206, industry_risk_map.json)
   modules/module3_going_concern (SFR-301~306, 하드룰=부록 B)
   modules/module4_crossval    (SFR-401~403, cross_validation.yaml)
   memo/generator              (SFR-404/405 고정 면책 문안)
   guards.py                   (SFR-604/606, NFR-REL-03)
   storage.py                  (인메모리 리포지토리 = PostgreSQL 자리)
```

| RFP 요구 | 구현 위치 |
|---|---|
| 부록 A Signal 공통 스키마 | `models.Signal` (evidence·confidence·rule_version·snapshot_id) |
| 부록 B 계속기업 지표·하드룰 | `modules/module3_going_concern.py` |
| 부록 D 도구 카탈로그 | `mcp_server.py` |
| SFR-C07 파싱 실패 등급 | `models.ParseIssue`, `service` job 상태(PARTIAL) |
| SFR-302 산업 왜곡 보정 | 수익 전 단계 → 현금 runway(`_cash_runway`) |
| 315→240 흐름 | KeyRisk.jet_updates → `get_jet_update_status` |

## 데이터 모드

- 기본 **fixture**(샘플 3사: 한빛건설=부실 건설, 대양제조=건전 제조, 제노바이오=수익 전 바이오).
- `SMARTRA_DART_API_KEY` 설정 시 **OpenDART REST**(`dart/rest_client.py`) 활성화 — 공식 API 사양 기반.
  구조화 엔드포인트(재무·감사의견·보수) 우선, 비정형 감사보고서 파싱은 best-effort(파싱 이슈로 표면화).

## 웹 쇼케이스 · 배포 (GitHub · Vercel)

라이브: **https://smart-ra.vercel.app** · 소스: **https://github.com/4aprilmayjune6/smart-ra**

- **GitHub**: 저장소 전체(MCP 서버·엔진·CLI·테스트·웹)를 올린다. DART 인증키는 환경변수로만 쓰며
  `.gitignore`(`.env`·`.venv/`·`output/`)로 커밋에서 제외한다. `.env.example` 참조.
- **Vercel**: 두 부분을 함께 배포한다.
  - **정적 쇼케이스** — `python scripts/build_web.py` 가 `output/` 의 메모·대시보드·RFP를 완전한
    HTML 문서로 감싸 `web/` 에 큐레이션한다(`vercel.json` `outputDirectory: web`).
  - **실시간 동적 검색** — `api/analyze.py`(회사·연도 → 실시간 DART 수집·분석 → 메모 HTML),
    `api/companies.py`(상장사 자동완성)의 **Python 서버리스 함수**. 랜딩(`web/index.html`)의 검색창이
    호출한다. `vercel.json` `functions.includeFiles` 로 `smart_ra` 엔진을 번들한다(`requirements.txt`,
    mcp 제외 경량).

**실데이터(실제 상장사) 활성화**: Vercel 프로젝트에 환경변수 `SMARTRA_DART_API_KEY`(OpenDART 인증키)를
설정하면 rest 모드로 전환돼 임의 상장사를 분석한다. 미설정 시 fixture 샘플 3사만 동작한다. 키는
**서버 환경변수로만** 두며 코드·응답·커밋에 넣지 않는다(NFR-SEC-04).

```bash
python scripts/build_web.py     # output/ → web/ (래핑·랜딩·키 스캔). 검색 UI 있는 index.html 은 보존
# 이후 GitHub push → Vercel 자동 재배포
```

상세 절차는 [`DEPLOY.md`](DEPLOY.md) 참조.

## 미구현 (Phase 2/3 — RFP 참조)

PostgreSQL/오브젝트 스토리지 영속화, Streamable HTTP + OAuth 2.1 전송, 승인 웹 콘솔(React),
docx/pdf 실제 내보내기, LLM 서술 모드, 감사인 변경 이력의 비정형 원문 파서, 백테스트 하네스,
8개 산업 전체 콘텐츠(현재 5개 초안). 산업맵·룰은 **발주사 SME 검수 대상**이다.

## 면책

산출물은 **자동 생성 초안**이며 감사인의 판단을 대체하지 않는다(메모 9절 고정 문안, SFR-405).
`industry_risk_map.json`·`cross_validation.yaml`의 감사 내용은 참조용 초안으로, 실제 사용 전
회계사(SME) 검수가 필요하다.
