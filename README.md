# 이 사이트 운영법

6개월 뒤에 봐도 알 수 있게 순서대로 적는다.

## 지금 상태 (2026-08-07) — Sanity 하나로 통일됨

글은 전부 **Sanity Studio**(브라우저에서 쓰는 CMS)에서 쓴다. 예전에 있었던
`posts/` 폴더 방식은 2026-08-07에 완전히 없앴다 — 실제 글 1편(이미지 포함)이
Sanity → 라이브까지 문제없이 도는 걸 확인한 뒤 지운 것이다. (예전 버전이 필요하면
git 이력에 남아있다.)

## 새 글 하나 올리기

**1. https://obssible.sanity.studio/ 접속.**

**2. 새 Post 만들기.** Title·Slug(오른쪽 "Generate" 버튼으로 제목에서 자동 생성)·Date·Body 채운다.

> ⚠️ **한 번 발행한 글의 Slug는 절대 바꾸지 마라.** 공유된 링크가 깨지고,
> 뉴스레터가 "이미 보낸 글"인지 판단하는 기준이라 중복 발송이 날 수 있다.

**3. Publish 누른다.**

**4. 끝.** Sanity 웹훅이 Netlify를 자동으로 재빌드시킨다 — git도, 터미널도 필요 없다.
Publish 후 대략 10~20초 안에 `obssible.com`에 뜬다.

## 화면으로 미리 보고 싶으면

```bash
SANITY_PROJECT_ID=gqrw1ms5 python build.py
python -m http.server 4173
```

브라우저에서 `localhost:4173` 을 연다.

## 글 고치기 / 지우기

Sanity Studio에서 해당 글을 열어 수정 후 Publish, 또는 문서 메뉴에서 삭제한다.
삭제하면 웹훅이 다시 돌면서 해당 글 페이지도 자동으로 사라진다.

## 어떤 파일을 만지고, 어떤 파일을 만지면 안 되나

**만지는 파일 (원본)**

| 파일 | 용도 |
|---|---|
| Sanity Studio 화면 | **글.** 터미널도 git도 필요 없다 |
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
2. 테스트들 (pytest) — Sanity 응답 처리, 주소 규칙, 템플릿, 보안
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

두 가지 경로가 있다.

**글을 쓸 때 (Sanity):**

```
Sanity Studio에서 Publish
        ↓ Sanity 웹훅이 Netlify Build Hook을 호출
Netlify가 requirements.txt 설치 → build.py 실행 (Sanity 서버에 물어봄)
        ↓
obssible.com 갱신 (Publish 후 대략 10~20초)
```

git도 터미널도 필요 없다.

**코드를 고칠 때 (`build.py`, `partials/`, `assets/style.css`, `studio-schema/` 등):**

```
파일 수정 → python check.py → git push
        ↓
Netlify가 GitHub push를 감지해서 같은 방식으로 재빌드
        ↓
obssible.com 갱신
```

**Sanity 웹훅 설정 위치**: `sanity.io/manage` → 프로젝트(`gqrw1ms5`) → API → Webhooks.
이름 `sanity-publish`, dataset `production`, filter `_type == "post"`, 대상은 Netlify의
Build Hook URL. 둘 다 이미 연결되어 있다 — 새로 설정할 필요 없음, 문제 생겼을 때 확인할
위치로만 기록해둔다.

## Sanity 설정하기 (참고용 — 이미 완료됨)

이 프로젝트는 이미 설정이 끝났다(프로젝트 ID `gqrw1ms5`, Studio는
https://obssible.sanity.studio/ ). 아래는 그때 어떻게 했는지 기록이다 —
새 프로젝트를 처음부터 다시 만들 일이 생기면 참고한다.

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

### 그다음 (이미 끝남)

- Netlify 환경변수 `SANITY_PROJECT_ID=gqrw1ms5` 설정 ✅
- Studio에서 실제 글 발행 → 사이트에 정상적으로 뜨는지 확인 ✅
- 이미지 업로드, RSS, 사이트맵, Buttondown까지 실제 데이터로 재검증 ✅
- Sanity 웹훅 → Netlify Build Hook 연결 (Publish하면 자동 재빌드) ✅
- `posts/` 경로와 `markdown-it-py` 제거 ✅ (2026-08-07)
