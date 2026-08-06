# 이 사이트 운영법

6개월 뒤에 봐도 알 수 있게 순서대로 적는다.

## 지금 상태 (2026-08-06) — 글쓰기 경로가 두 개다

**Sanity**(브라우저에서 글 쓰는 전문 도구)로 옮기는 중인데, 아직 완전히 검증되지 않아서
**예전 방식(`posts/` 폴더에 마크다운 파일)도 그대로 살아있다.** 둘 다 동시에 작동한다 —
어느 쪽으로 글을 써도 사이트에 나온다.

- 아직 Sanity 설정을 안 했다면 → 이 문서 그대로, `posts/` 폴더 방식 (아래 "새 글 하나 올리기")
- Sanity를 쓰고 싶다면 → 맨 아래 "Sanity 설정하기" 섹션부터

**한쪽이 완전히 실제로 검증되기 전까지는 예전 방식을 지우지 않는다.** 이건 규칙이다 —
글 쓸 방법이 하나도 없는 상태가 되는 걸 막기 위해서다.

## 새 글 하나 올리기 — `posts/` 폴더 방식 (지금 당장 되는 방법)

**1. `posts/` 폴더에 마크다운 파일을 하나 만든다.**

파일 이름은 아무거나 상관없다. 웹 주소는 파일 이름이 아니라 아래 `slug` 값으로 정해진다.

**2. 맨 위에 이 세 줄을 넣는다.**

```
---
title: 글 제목
date: 2026-08-06
slug: 원하는-주소
---
```

- `title` — 페이지 제목
- `date` — 목록 정렬 기준(최신순)이자 화면에 보이는 날짜
- `slug` — 웹 주소가 된다. `slug: my-first-log` 이면 `obssible.com/log/my-first-log/`

> ⚠️ **한 번 발행한 글의 `slug`는 절대 바꾸지 마라.** 공유된 링크가 깨지고,
> 뉴스레터가 "이미 보낸 글"인지 판단하는 기준이라 중복 발송이 날 수 있다.

**3. 본문을 마크다운으로 쓴다.**

표준 마크다운(CommonMark) + 표·취소선을 전부 지원한다:

| 쓰면 | 결과 |
|---|---|
| `## 소제목` | 소제목 — **본문은 여기서부터 시작해라.** `#`(가장 큰 제목)은 페이지 제목 자리라 겹친다 |
| 그냥 줄글 | 문단 |
| `- 항목` / `1. 항목` | 목록 (번호·중첩 다 됨) |
| `> 인용문` | 인용문 |
| `` `코드` `` | 코드체 |
| ` ```코드블록``` ` | 코드블록 (긴 줄은 안에서만 옆으로 스크롤) |
| `**굵게**` / `*기울임*` / `~~취소선~~` | 굵게 / 기울임 / 취소선 |
| `[글자](주소)` | 링크 |
| `![대체글](주소)` | 이미지 |
| 표 | 표 |
| `---` | 구분선 |

> 🚨 **아직 안 되는 것**: 체크박스 목록(`- [ ] 할일`)만 예외다. 대괄호가 글자 그대로 나온다.
> 흔히 쓰는 문법은 아니라 지금은 안 넣었다.

> 🔒 **원시 HTML은 안 통한다.** `<script>`처럼 직접 HTML 태그를 붙여넣으면 코드가 실행되지
> 않고 화면에 그 글자 그대로 보인다. 의도한 안전장치다.

**4. 검사를 돌린다.**

```bash
python check.py
```

전부 통과하면 다음으로 간다. 실패하면 무엇이 잘못됐는지 화면에 나온다.

**5. GitHub에 올린다.**

```bash
git add -A
git commit -m "새 로그: 제목"
git push
```

**6. 끝.** Netlify가 알아서 빌드해서 `obssible.com`에 올린다. 몇 십 초 걸린다.

## 화면으로 미리 보고 싶으면

```bash
python build.py
python -m http.server 4173
```

브라우저에서 `localhost:4173` 을 연다.

## 글 고치기 / 지우기

`posts/` 안의 `.md` 파일을 고치거나 지우고 4~5번을 다시 하면 된다.
지우면 해당 글 페이지도 자동으로 사라진다.

## 어떤 파일을 만지고, 어떤 파일을 만지면 안 되나

**만지는 파일 (원본)**

| 파일 | 용도 |
|---|---|
| `posts/*.md` | **글 (예전 방식).** Sanity 검증 끝나면 없어질 예정 |
| Sanity Studio 화면 | **글 (새 방식).** 터미널도 git도 필요 없다 |
| `studio-schema/post.js` | Sanity에 "글은 이런 모양이다"라고 알려주는 설정. Studio 만들 때 한 번만 씀 |
| `partials/home-template.html` | 홈 화면 내용 |
| `partials/about-template.html` | About 페이지 내용 |
| `partials/post-template.html` | 글 페이지 틀 |
| `partials/list-template.html` | 글 목록 틀 |
| `partials/nav.html` | 상단 메뉴 (한 곳만 고치면 전체 반영) |
| `assets/style.css` | 사이트 전체 디자인 |

**절대 만지면 안 되는 파일 (자동 생성)**

`index.html`, `about.html`, `log/`, `rss.xml`, `sitemap.xml`

빌드할 때마다 **통째로 지워지고 새로 만들어진다.** 여기를 고쳐도 다음 빌드에 사라진다.
그래서 git에도 저장하지 않는다.

## 주소 규칙 (2026-08-06 확정, 변경 금지)

```
홈       obssible.com/
글 목록   obssible.com/log/
글        obssible.com/log/<slug>/
소개      obssible.com/about.html
```

## 검사가 무엇을 보는가

`python check.py` 가 순서대로 확인하는 것:

1. 코드 스타일 (ruff)
2. 테스트들 (pytest) — 마크다운 변환, Sanity 응답 처리, 주소 규칙, 템플릿, 보안
3. `requirements.txt`에 정확한 버전이 박혀 있는가
4. 빌드가 성공하는가
5. **빌드를 두 번 해도 결과가 같은가**
6. 모든 페이지에 제목·설명·소셜태그·파비콘·분석·h1 이 있는가
7. RSS와 사이트맵이 유효한가
8. **내부 링크가 다 살아있는가**
9. 자동 생성 파일이 실수로 git에 들어가지 않았는가

GitHub에 올리면 같은 검사가 자동으로 한 번 더 돈다. **이 검사는 Sanity 서버에 실제로 접속하지
않는다** — 가짜 응답을 흉내 낸 데이터로 테스트하기 때문에, Sanity가 그 순간 느리거나 잠깐
멈춰도 검사 결과에는 영향 없다.

## 처음 세팅할 때 한 번만

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## 배포 구조

```
posts/*.md 수정 또는 Sanity에 발행
        ↓
   git push (posts/를 고쳤을 때만 필요 — Sanity는 push 없이 바로 반영)
        ↓
Netlify가 requirements.txt 설치 → build.py 실행
        ↓ build.py가 이 순간 Sanity 서버에 물어봄
obssible.com 갱신
```

**Sanity로 글을 쓰면 git push가 필요 없다.** 다만 지금은 Netlify가 push를 받아야만
다시 빌드하므로, Sanity에만 새 글을 올렸을 때 사이트에 바로 반영되진 않는다 — 이건
검증이 끝나면 자동으로 다시 빌드되도록 손볼 항목이다. 지금 당장은 Sanity에 글을 쓴
다음 아무 빈 커밋이나 하나 올리면 (`git commit --allow-empty -m "rebuild"`) 강제로
새로고침된다.

## Sanity 설정하기 (처음 한 번만)

### 👤 당신이 직접 할 것

**1. Sanity 계정과 프로젝트 만들기**

터미널에서 (이 컴퓨터에 Node.js가 이미 깔려있다):

```bash
npm create sanity@latest
```

실행하면 로그인 창(브라우저)이 뜬다. 로그인 후 아래처럼 답하면 된다:

| 물어보는 것 | 답 |
|---|---|
| 프로젝트 이름 | 아무거나 (예: `obssible`) |
| 데이터셋 이름 | 기본값(`production`) 그대로 엔터 |
| 템플릿 | **"Clean project with no predefined schema types"** (스키마 없는 빈 프로젝트) — 내가 만든 스키마를 쓸 거라서 |
| TypeScript? | **아니오(No)** — 내가 준 파일이 순수 자바스크립트라 그게 더 간단하다 |
| 데이터셋 공개 여부(public/private) | **public** — 이래야 `build.py`가 비밀키 없이 글을 읽어올 수 있다 |

**2. 내가 만든 스키마 파일 넣기**

방금 생긴 프로젝트 폴더 안에 `schemaTypes` 폴더가 있을 것이다. 이 저장소의
`studio-schema/post.js` 파일을 그 안에 그대로 복사한다.

그다음 `schemaTypes/index.js`(또는 `.ts`)를 열어서 이렇게 되어 있는지 확인:

```js
import { postType } from "./post";

export const schemaTypes = [postType];
```

**3. Studio를 배포한다**

```bash
npx sanity deploy
```

주소를 물어보면 원하는 이름으로 (예: `obssible` → `obssible.sanity.studio`).
끝나면 그 주소로 브라우저에서 접속해서 글을 쓸 수 있다.

**4. 프로젝트 ID를 나한테 알려주기**

`sanity.config.js` 파일을 열면 맨 위에 `projectId: 'abc12345'` 같은 줄이 있다.
그 `abc12345` 부분(프로젝트 ID)을 복사해서 나한테 알려달라.

### 그다음은 내가 한다

프로젝트 ID를 받으면:
- Netlify에 그 값을 환경변수(`SANITY_PROJECT_ID`)로 설정하는 방법을 안내
- 실제로 Studio에서 글 하나를 써달라고 요청 → 사이트에 정상적으로 뜨는지 함께 확인
- 이미지 업로드, RSS, 사이트맵까지 전부 실제 데이터로 재검증
- 전부 확인되면 `posts/` 경로를 없애는 작업을 별도로 진행 (지금은 안 함)
