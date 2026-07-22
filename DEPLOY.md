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
