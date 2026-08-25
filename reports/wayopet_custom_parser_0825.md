# wayopet.com 커스텀 파서 (우선순위 3, 2026-08-25)

## 배경

`reports/new_source_procurement_0825.md`가 wayopet.com(다수 자격증 훈련사가
답변하는 Q&A 플랫폼)을 "저자 다양성에 특히 좋은 소스"로 지목했으나, 기존
`mini_blog_scraper.py`의 generic 추출기(`<article>`/`<main>` 태그 탐색)가
6건 전부 "본문 미검출"로 드랍시켰다. 원인 미규명 상태로 남겨져 있었다.

## 원인 진단

raw HTML 백업(`data/reviews/`가 아니라 스크레이퍼 자체의 `raw/*.html`)을 직접
열어 확인한 결과:

- wayopet.com은 **Next.js SSR 앱**(`id="__next"`, CSS-module 해시 클래스만
  존재, `<article>`/`<main>` 태그 없음)이다. `<div style="...">` 인라인
  스타일 위주라 안정적인 CSS 선택자가 없다.
- 다만 콘텐츠는 **서버사이드 렌더링돼 있어 헤드리스 브라우저는 불필요**하다
  (본문 밖 스크립트 태그를 제외해도 한글 6,038자가 확인됨 — `__NEXT_DATA__`
  JSON은 3,810자뿐이라 페이지 설정용이지 본문 소스가 아니다).
- 대신 **사이트 전체가 공유하는 리터럴 텍스트 마커**로 본문 구간을 자를 수
  있다: 시작 `"와요 회원님의 질문"`, 끝(광고/CTA 블록) `"여기까지 읽어본"`.
  같은 Q&A가 페이지에 두 번(반응형 레이아웃 추정) 렌더링되는데, 첫 번째
  마커 쌍만 쓰면 자동으로 중복이 걸러진다.

## 구현

`scrapper/mini_blog_scraper.py`(사용자 소유 도구)에 최소 침습으로 확장했다 —
기존 naver_blog/tistory 처리 로직은 그대로 두고, `to_fetch_url()`에
wayopet.com 분기와 `extract_wayopet()` 함수만 추가했다.

- 마커 슬라이싱 후 페이지네이션 잔재("1", "/", "1 / 2")를 정규식으로 제거.
- 트레이너 프로필 카드("{이름}\n훈련사\n프로필 보기\n경력 및 자격...")는
  숫자(답변수·만족도%)가 페이지네이션 필터에 함께 잘려 어색하게 남길래,
  카드 전체를 답변 마지막 문장(면책 문구) 선에서 잘라냈다.
- **`author` 필드는 site명이 아니라 답변자 훈련사명**("박\*준" 등, 마스킹된
  실명)으로 채운다 — 질문자(보호자)는 익명 닉네임이라 저자로 보지 않았다.
  `"{이름} 훈련사님의 답변"` 패턴을 정규식으로 파싱해서 뽑는다.

## 검증 결과 — 6/6 성공, 저자 3명

| doc_id | 저자 | 글자수 |
|---|---|---:|
| wayopet-wayopet-qsf79xhviuzawne7 | 박\*준 | 2,077 |
| wayopet-wayopet-02lex4hfdxkjgh6s | 황\*규 | 1,768 |
| wayopet-wayopet-mzzejqwpdocmik7h | 박\*준 | 2,742 |
| wayopet-wayopet-aoeveog0gsdb51og | 박\*준 | 2,433 |
| wayopet-wayopet-vxk7gfhycftogk1v | 김\*이 | 2,133 |
| wayopet-wayopet-sryjhpaqmdvfy28v | 박\*준 | 3,596 |

**6페이지에서 서로 다른 훈련사 3명** — easiestip.com(1인 경험담, 저자 1명)·
핏펫(기업 계정, 저자 1명)보다 이 소스가 저자 다양성 면에서 명확히 낫다.
콘텐츠도 "원인 분석 → 솔루션 제안(번호 매긴 단계)" 구조가 일관돼 절차형
훈련 콘텐츠로도 유용하다.

## 이번에 하지 않은 것

- **MANIFEST 등록·실제 인제스트는 하지 않았다** — 오늘 이미 코퍼스 확장을
  한 번 성공시켰고(`reports/corpus_expansion_diverse_0825.md`), 검색 게이트도
  막 전환했다(`reports/retrieval_gate_redesign_retry_0825.md`). 변수를 한
  번에 너무 많이 움직이지 않기 위해 이번엔 **파서 구축 + 스테이징까지만**
  한다. 실제 인제스트·재평가는 다음 라운드로 넘긴다.
- 6건 외 wayopet.com의 나머지 Q&A(사이트에 훨씬 많을 것으로 추정)는 추가
  조달하지 않았다 — 파서가 실제로 동작하는지 검증하는 것이 이번 범위였다.

## 산출물

- `scrapper/mini_blog_scraper.py` (수정 — `to_fetch_url`·`extract_wayopet`
  추가, 기존 naver_blog/tistory 로직 미변경)
- `scrapper/data/blog_raw_wayopet_0825/posts.jsonl` (6건, 향후 `CRAWL_POOLS`에
  추가하면 바로 쓸 수 있는 형태)
- `data/raw/documents_candidate_0825_wayopet/*.md` (6건, `status: NOT_INGESTED`)

## 다음

새 코퍼스 확장 라운드(다음 세션)에서 easiestip 6건 때와 같은 방식으로
`blog_raw_wayopet_0825`를 `CRAWL_POOLS`에, 6건을 `MANIFEST`에 추가하고
`run_combined_retrieval_eval.py`로 재평가할 것. wayopet.com에 더 많은 Q&A가
있을 가능성이 높으니 목록 페이지 크롤링(카테고리별 글 URL 수집)도 다음
후보다.
