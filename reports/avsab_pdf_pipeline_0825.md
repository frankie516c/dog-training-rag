# AVSAB PDF 인제스트 파이프라인 (Track F, 2026-08-25)

새 스크립트 `scripts/ingest_pdf_documents.py`로 AVSAB(미국수의행동학회) 포지션
스테이트먼트 3건을 PDF에서 추출·청킹했다. **아직 `ingest_documents.py`의
MANIFEST에는 등록하지 않았다** — 이번 산출물은 전부 `NOT_INGESTED` 상태의
후보다.

## 처리 결과

| doc_id | 청크 | 총 문자 | 최대 청크 |
|---|---:|---:|---:|
| avsab-humane-dog-training-2021 | 48 | 21,571 | 480 |
| avsab-puppy-socialization-2014 | 16 | 6,962 | 476 |
| avsab-dominance-theory-2014 | 51 | 22,735 | 479 |

셋 다 `scripts/chunking_config.py`의 v3 계약(target 420 / min 150 / max 480)을
그대로 따랐고 480자 초과 0건. 청크 레코드 스키마는 `ingest_documents.py`의
문서 청크와 동일(`schema_version`, `chunk_id`, `doc_id`, `chunk_index`,
`source_url`, `slot`, `chunking_method`, `heading_path`, `text`, `char_count`,
`embedding_eligible`, `chunking`) — `run_combined_retrieval_eval.py`의
`load_document_chunks()`가 기대하는 필드를 전부 채운다.

## 설계 — 왜 `ingest_documents.py`를 그대로 안 썼나

이 문서는 영어 PDF고, 기존 헤딩 승격 로직(`promote_headings`/`is_hard_wrapped`)은
한국어 문장 종결 어미("다.", "습니다." 등)에 튜닝돼 있어 영어 텍스트엔 안
맞는다. 대신 짧은(2~6쪽) 포지션 스테이트먼트라는 특성을 살려 헤딩 탐색 없이
"한 개 리드 섹션 + 문자 예산 패킹"만으로 처리했다 — `split_sections`·
`split_chars`·`chunk_id_for`·`check_url_allowed`·`CHUNK_SCHEMA_VERSION`은
`ingest_documents.py`에서 그대로 import해 재사용했다(로직 중복 없음).

## PDF 추출 품질

- 라이브러리: `pypdf`(신규, `uv add`로 추가— `pip install` 미사용).
- 매 페이지 반복되는 마스트헤드/푸터("American Veterinary Society...",
  "www.AVSAB.org", 페이지 번호만 있는 줄)를 필터링해 청크에 안 들어가게 함.
- 스마트따옴표·리거처(fi/fl) 깨짐 문자를 정규화. 최종 산출물에 `�` 문자
  없음(전수 grep 확인).
- **알려진 한계**: 원본 PDF가 정당화된 두 단 레이아웃이라 일부 단어가
  줄바꿈 지점에서 하이픈으로 쪼개진 채로 추출됨(예: "vac- cination",
  "maternal immunity ,"). 이번엔 자동 병합을 넣지 않았다 — 하이픈 자동
  병합은 정말 합성어인 경우와 구분이 안 돼 잘못 붙일 위험이 있어서다.
  임베딩 검색에는 치명적이지 않을 것으로 보이나(추정, 미측정) 사람이
  실제 청크를 읽을 때는 거슬릴 수 있다.

## 저작권/이용조건 — [주의]

AVSAB 사이트(`avsab.org/resources/position-statements/`)에 PDF 재이용에
대한 명시적 라이선스 문구는 없었다(WebFetch로 확인). 로그인·유료 구간이
아니고 "지역 인쇄소에서 인쇄 가능"이라 공개 배포를 전제한 문서로 보이지만,
명문 허가는 아니다. 이 저장소의 기존 정책(`docs/SOURCES.md`, 개인 학습·
비공개 전제)과 같은 수준의 판단으로 진행했다 — 공개·서비스화 전환 시
재확인 필요.

## 산출물

- `scripts/ingest_pdf_documents.py` (신규)
- `pyproject.toml`에 `pypdf` 의존성 추가(`uv add`)
- `data/raw/documents_candidate_0825_avsab/*.{md,jsonl}` + `pdf_ingest_log.json`
  (전부 gitignore 대상, `status: NOT_INGESTED`)
- 원본 PDF는 `data/scratch/avsab_pdf_raw/*.pdf`에 로컬 보관(재배포 목적 아님,
  gitignore 대상)

## 다음 단계 (실행 안 함 — 사람/다른 트랙 결정 사항)

실제 `MANIFEST` 등록 여부는 이번 라운드 범위 밖이다. 등록하게 되면
`CRAWL_POOLS`처럼 문서 소스 종류(HTML/PDF)를 구분하는 필드를
`ingest_documents.py`의 MANIFEST 스키마에 추가할지, 아니면 이 PDF 파이프라인의
산출물을 별도 CRAWL 경로로 취급할지 결정이 필요하다. 오늘 코퍼스 확대
실패(`reports/corpus_expansion_0825.md`, 근접 중복 콘텐츠로 성능 하락)의
교훈대로, AVSAB 3건을 실제로 합칠 때도 반드시 재평가(`run_combined_retrieval_eval.py
--graph-off`)로 회귀 여부를 확인해야 한다 — 다만 이번 건은 완전히 다른 저자
(공식 학회)이자 완전히 다른 장르(공식 입장문 vs 블로그 서사)라 근접 중복
위험은 낮을 것으로 예상한다(추정, 미검증).
