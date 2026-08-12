# 배포 가이드 — GitHub · Vercel

이 저장소는 두 부분으로 나뉜다.

| 대상 | 무엇 | 위치 |
|---|---|---|
| **GitHub** | 전체 코드 — MCP 서버·결정론 엔진·CLI·테스트 | 저장소 전체 |
| **Vercel** | 산출물 **정적 쇼케이스**(메모·대시보드·RFP) | `web/` (빌드 불필요) |

> Vercel은 stdio 기반 MCP 서버 **본체를 그대로 실행하지 않는다**. MCP 서버는 GitHub에서
> 받아 로컬(또는 사내 서버)에서 `claude mcp add` 로 구동한다. Vercel에는 산출물만 올린다.

---

## 0. 커밋 전 보안 점검 (필수)

DART 인증키는 **환경변수(`SMARTRA_DART_API_KEY`)로만** 쓰고 어떤 파일에도 넣지 않는다.
저장소에 키가 없는지 재확인:

```bash
git grep -nE "[0-9a-f]{40}" -- . ':!web/*.pdf'   # 40자 hex(키 형태) 검색 → 결과 없어야 정상
```

`.gitignore` 가 `.env`, `.venv/`, `output/` 를 제외한다. `.env.example` 만 커밋한다.

---

## 1. GitHub 업로드

```bash
# 저장소 루트에서
git init
git add .
git commit -m "SMART-RA 참조구현 + 정적 쇼케이스"

# GitHub에 빈 저장소를 먼저 만든 뒤(웹 또는 gh):
gh repo create smart-ra --private --source=. --remote=origin --push
#  ↑ gh CLI 로그인 필요(gh auth login). 또는 수동:
# git remote add origin https://github.com/<사용자>/smart-ra.git
# git branch -M main
# git push -u origin main
```

`web/index.html` 푸터의 GitHub 링크(`https://github.com/`)를 실제 저장소 URL로 바꾼 뒤
`python scripts/build_web.py` 를 다시 돌리면 반영된다(또는 `web/index.html` 직접 수정).

---

## 2. Vercel 배포 (정적 쇼케이스)

### 방법 A — 대시보드 Import (권장)

1. https://vercel.com/new → **Import Git Repository** → 이 저장소 선택
2. 설정 확인:
   - **Framework Preset**: `Other`
   - **Build Command**: 비움(또는 `vercel.json` 값 그대로)
   - **Output Directory**: `web`
   - **Install Command**: 비움
3. **Deploy**. `vercel.json` 이 위 값을 이미 지정하므로 대부분 그대로 두면 된다.

> 자동 인식이 어긋나면 프로젝트 **Settings → General → Root Directory** 를 `web` 으로 지정하고
> Build/Install Command 를 비운다. `web/` 안이 완결된 정적 사이트라 빌드가 필요 없다.

### 방법 B — Vercel CLI

```bash
npm i -g vercel
vercel            # 최초 배포(프리뷰). 프롬프트에서 Output Directory = web
vercel --prod     # 프로덕션 배포
```

### 배포 후

- 랜딩: `https://<프로젝트>.vercel.app/`
- 개별: `/memo-amore-2025`, `/dashboard`, `/rfp` (cleanUrls 로 `.html` 생략 가능)
- PDF: `/memo-amore-2025.pdf`

키가 필요 없다(정적 산출물만 서빙). 실데이터 분석은 로컬 MCP/CLI에서 수행한 결과를 올리는 구조다.

---

## 3. 쇼케이스 갱신

새 산출물을 `output/` 에 생성한 뒤:

```bash
python scripts/build_web.py     # output/ → web/ 재빌드(래핑·랜딩 재생성·키 스캔)
git add web && git commit -m "쇼케이스 갱신" && git push
```

Vercel은 push마다 자동 재배포한다.

---

## 4. 실시간 동적 검색 (아키텍처 · 활성화)

랜딩(`/`)의 검색창 흐름:

```
정적 web/companies.json (회사명·종목코드 → corp_code)   ← 자동완성·클라이언트 해석
        │  선택 시 corp_code 전송
        ▼
GET /api/analyze?corp=<corp_code>&year=<YYYY>          ← api/analyze.py (서버리스)
        │  register_by_corp_code → 병렬 DART 수집 → 결정론 엔진 → 메모 HTML
        ▼
        메모 HTML (iframe 표시)
```

**설계 제약과 대응**:
- **corpCode.xml(약 3.6MB)은 서버리스에서 못 받는다** — DART가 클라우드 IP로의 대용량 전송을
  ~14KB/s로 스로틀해 60초 함수 한도를 초과(≈256초). 그래서 회사명↔corp_code 매핑은 **정적
  `web/companies.json`** 으로 두고, 분석은 **corp_code 로 직접**(작은 호출만) 수행한다.
- **HTTP 는 표준 라이브러리 urllib** 사용 — httpx 는 Vercel 런타임에서 요청이 멈춘다.
- 개별 DART 호출(공시·연도별 재무·감사)은 **ThreadPoolExecutor 로 병렬** 수집 → 실데이터 메모
  약 5~15초.

### 4-1. DART 키 설정 (Vercel 환경변수)

키는 **서버 환경변수로만** 둔다(코드·응답·커밋 금지, NFR-SEC-04). 채팅·화면에 노출된 키는 폐기하고
[opendart.fss.or.kr](https://opendart.fss.or.kr/) 에서 **재발급**한 새 키를 쓴다.

- **대시보드**: 프로젝트 **smart-ra → Settings → Environment Variables** → Key `SMARTRA_DART_API_KEY`,
  Value `<재발급 키>`, **Production** → Save → **Redeploy**(env 변경은 재배포 후 반영).
- **CLI**: `vercel env add SMARTRA_DART_API_KEY production` (프롬프트에 키 붙여넣기) → `vercel deploy --prod`.

### 4-2. 상장사 목록 생성 (`web/companies.json`)

corpCode.xml 은 **로컬(국내 IP)** 에서 한 번 받아 정적 목록으로 만든다(저장소엔 기본으로 삼성전자
시드만 들어 있다). 회원 터미널에서:

```bash
# 키는 로컬 환경변수로만(저장소로 안 감)
$env:SMARTRA_DART_API_KEY="<재발급 키>"        # PowerShell
.venv\Scripts\python scripts\gen_companies.py  # → web/companies.json (상장사 전체)
git add web/companies.json && git commit -m "상장사 목록 갱신" && git push
```

### 확인

```bash
curl "https://<프로젝트>.vercel.app/companies.json"                         # 상장사 목록(정적)
curl "https://<프로젝트>.vercel.app/api/analyze?corp=00126380&year=2024"    # 삼성전자 실데이터 메모
```

> 공개 엔드포인트이므로 남용 시 일일 쿼터(약 20,000건) 소모에 유의한다. 트래픽이 커지면
> per-IP rate-limit·결과 캐시 도입을 권장한다.
