# Neo4j 적재 핸드오프

Stage 2 추출(73청크)까지 끝났고 Neo4j 적재만 남았습니다. 이 문서만 읽고 바로 시작할
수 있도록 쓴 것입니다.

**막힌 지점**: Docker Desktop이 WSL 선택적 구성 요소 없이 기동하지 못합니다
(`Wsl/WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED`). 관리자 권한과 재부팅이 필요해서
2026-08-19 세션에서는 여기서 멈췄습니다. 아래 1번이 그 해결입니다.

> **2026-08-20 재적재** — 슬롯 3 `mypetlife-kennel-training` 문서가 저작권
> 사유(무단복제 무관용 공지 + 유료 콘텐츠)로 사후 제거되어(자세한 경위는
> `docs/acquisition_list.md`의 3-2 항목 참고), 그 문서의 청크 4개를 뺀
> `extractions_stage2.jsonl`(75→71건)로 그래프를 `--wipe` 재적재했습니다.
> **현재 실측값은 252노드·101엣지**이고, 아래 5번 대조표와 이 문서의 다른
> 수치들도 전부 이 재적재 기준 실측값으로 갱신했습니다 (이전 값 265노드·107엣지는
> mypetlife 포함 상태였던 값이라 더 이상 유효하지 않습니다).
>
> <details><summary>이전 기록 (mypetlife 포함 상태, 2026-08-20 최초 적재)</summary>
>
> **2026-08-20 완료** — **적재까지 끝났습니다.** 재부팅 후 Docker 데몬이 정상
> 기동했고(WSL 기본 버전 2), Neo4j 5.26.29 컨테이너에 265노드·107엣지를 적재해
> 5번 대조표를 실 DB에서 검증했습니다. 아래 1·2번은 이제 참고용이고, 컨테이너가
> 멈춰 있으면 `docker start neo4j-graphrag`로 재개하면 됩니다. 남은 일은 6번
> (화면 캡처)과 미해결 항목들입니다.
>
> <details><summary>이전 갱신 (재부팅 대기 시점)</summary>
>
> **2026-08-20 갱신** — 구성 요소는 이미 설치돼 있고 **재부팅만 남았습니다.**
> `Win32_OptionalFeature` 조회에서 `Microsoft-Windows-Subsystem-Linux`와
> `VirtualMachinePlatform`이 둘 다 `InstallState 1 (Enabled)`, CBS
> `RebootPending`이 `True`입니다. 즉 1번의 관리자 명령은 지난 세션에 이미 먹혔고
> 재부팅이 안 됐을 뿐입니다. **재부팅부터 하고, 그래도 같은 에러가 나면 그때 1번을
> 실행하세요.** 4번(드라이버 설치·dry-run)은 끝나 있으니 재부팅 후엔 3번부터입니다.
>
> </details>
>
> </details>

## 사전 확인 — 이미 되어 있는 것

| 항목 | 상태 | 위치 |
|---|---|---|
| Stage 2 추출 71/73 (격리 2, mypetlife 제거 반영) | 완료 | `data/graph/extractions_stage2.jsonl` |
| alias 테이블 (3항목) | **수정 완료** | `data/graph/entity_aliases.json` |
| 쿼리 방향 수정 | **수정 완료** | `scripts/preview_queries.py`, 아래 5번 Cypher |
| 로더 | **실 DB 적재 완료·검증됨** | `scripts/load_graph_neo4j.py` |
| `neo4j` 드라이버 | **설치 완료** (6.2.0) | `pyproject.toml` / `uv.lock` |
| dry-run 재검증 | **완료** — 5번 대조표 4줄 모두 일치 | 2026-08-20 |
| Neo4j 컨테이너 | **기동 완료** (neo4j:5 → 5.26.29) | `neo4j-graphrag` |
| 실 DB 적재 | **완료** — 대조표 4줄 모두 일치 | 2026-08-20 |
| `NEO4J_PASSWORD` | `.env`에 있음, 8자로 최소 길이 통과 | 커밋되지 않음 (gitignore) |

`data/*`는 gitignore라 **추출물과 alias 테이블은 이 PC에만 있습니다.** 다른 기기에서
이어받는 경우 두 파일을 먼저 옮겨야 합니다.

### alias 테이블 내용

```json
{
  "슬개골 탈구": "슬개골탈구",
  "분리불안증": "분리불안",
  "분리불안 훈련": "분리불안"
}
```

**name만 정규화하고 `(name, type)` 쌍은 유지합니다.** `분리불안(문제행동)`과
`분리불안(질환)`은 별도 노드로 남습니다. 이 스키마의 `감별필요`가 문제행동→질환으로
가기 때문에, 둘을 합치면 엣지가 해소되는 게 아니라 사라집니다.

### 쿼리 방향 — 왜 뒤집었는가

`감별필요`는 `(증상|문제행동) → (질환)` 방향입니다. 즉 **질환 이름은 항상 화살표를
받는 쪽**입니다. 최초 쿼리는 질환을 시작점으로 잡아서, 매칭되는 엣지가 19개 있는
그래프에서 0건을 반환했습니다. 아래 5번 Cypher는 방향을 고친 버전입니다.

---

## 1. WSL 구성 요소 설치 (관리자 PowerShell)

**관리자 권한**으로 PowerShell을 연 뒤:

```powershell
wsl.exe --install --no-distribution
```

실행 후 **재부팅**합니다. 배포판은 필요 없습니다 — Docker Desktop이 자체 WSL 백엔드를
씁니다.

재부팅 후 확인:

```powershell
wsl --status
```

`WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED`가 더 이상 안 나오면 성공입니다.

## 2. Docker 기동 확인

Docker Desktop을 실행한 뒤:

```powershell
docker version
```

`Server:` 섹션에 버전이 찍히면 데몬이 살아 있는 것입니다.
`Error response from daemon: Docker Desktop is unable to start`가 나오면 1번이
덜 된 것입니다. **`docker info`가 exit 0을 반환해도 `Server:` 블록이 에러일 수
있으니 출력을 눈으로 확인하세요** — 지난 세션에서 이걸로 한 번 속았습니다.

## 3. Neo4j 컨테이너 실행

비밀번호는 `.env`의 `NEO4J_PASSWORD`에서 읽습니다. 문서에 적지 않습니다.

```powershell
$pw = ((Get-Content .env | Where-Object { $_ -like 'NEO4J_PASSWORD=*' }) -split '=', 2)[1]
docker run -d --name neo4j-graphrag -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/$pw -v neo4j-graphrag-data:/data neo4j:5
```

- bolt `7687`, browser `7474`, DB명은 기본값 `neo4j`
- 볼륨을 붙였으므로 컨테이너를 지워도 그래프는 남습니다
- Neo4j는 비밀번호 8자 이상을 요구합니다

기동 확인 (로그에 `Started.`가 뜰 때까지 10~30초):

```powershell
docker logs neo4j-graphrag --tail 20
```

브라우저에서 `http://localhost:7474` → 계정 `neo4j` / `.env`의 비밀번호.

## 4. 로더 실행

드라이버가 아직 설치돼 있지 않습니다:

```powershell
uv add neo4j
```

연결 없이 접기 결과만 먼저 확인 (권장):

```powershell
uv run python scripts/load_graph_neo4j.py --dry-run
```

기대 출력:

```
청크 71 · 노드 252 · 엣지 101 · 해소 실패 관계 0
```

적재:

```powershell
uv run python scripts/load_graph_neo4j.py
```

다시 돌려도 안전합니다 — 노드는 `(name, type)`, 엣지는 `(source, type, target)`으로
MERGE합니다. 그래프를 비우고 다시 넣으려면 `--wipe`를 붙입니다.

격리 2건은 `extractions_stage2.jsonl`에 애초에 없으므로 따로 걸러낼 것이 없습니다.

## 5. 확인용 Cypher 세 개

Neo4j Browser(`http://localhost:7474`)에서 실행합니다.

**① 분리불안으로 들어오는 경로 (1~2홉)**

```cypher
MATCH p=(b)-[:감별필요|완화한다|금기*1..2]->(a)
WHERE a.name CONTAINS '분리불안'
RETURN p LIMIT 5
```

**② 슬개골탈구 감별 경로**

```cypher
MATCH p=(b)-[:감별필요]->(a)
WHERE a.name CONTAINS '슬개골'
RETURN p LIMIT 5
```

**③ 타입별 집계** (두 개를 따로 실행)

```cypher
MATCH (n) RETURN n.type AS type, count(n) AS count ORDER BY count DESC
```

```cypher
MATCH ()-[r]->() RETURN type(r) AS relation, count(r) AS count ORDER BY count DESC
```

> 한글 관계 타입이 파서에서 걸리면 백틱으로 감싸세요:
> ``[:`감별필요`|`완화한다`|`금기`*1..2]``

### 기대값 — 오프라인 예측과 대조

`scripts/preview_queries.py`가 DB 없이 같은 순회를 파이썬으로 재현한 값입니다.
**실제 Cypher 결과가 아래와 다르면**, 접기 로직과 Neo4j의 MERGE 의미가 갈렸다는
뜻이니 그때는 적재를 신뢰하지 말고 원인부터 보세요.

> 아래 수치는 **2026-08-20 재적재(슬롯 3 mypetlife-kennel-training 제거 반영)
> 기준 실측값**입니다. 제거 전 값(경로 28/19, 노드 265, 관계 107)은 더 이상
> 유효하지 않습니다 — ①의 경로 수만 27로 줄었고, ②·시드 종점 수는 이 문서가
> 슬개골 축과 무관해 그대로입니다.

| 쿼리 | 기대 |
|---|---|
| ① 분리불안 | 경로 **27**개 (시드 노드 3개 — 아래 주 참고) |
| ② 슬개골 | 경로 **19**개 (시드 노드 3개 — 아래 주 참고) |
| ③ 노드 | **252** — 증상 70 · 문제행동 56 · 훈련법 48 · 질환 20 · 견종 18 · 용품 18 · 원칙 14 · 연령대 8 |
| ③ 관계 | **101** — 감별필요 58 · 완화한다 25 · 악화시킨다 9 · 선행조건 8 · 금기 1 |

> **시드 노드 수는 대조 지표가 아닙니다.** 위 3개는 `preview_queries.py:85,98`이
> **이름이 매칭되는 노드를 전부** 센 값이고, Cypher에서 `count(DISTINCT a)`로 세면
> **경로가 실제 도달한 종점만** 나와 ①은 2, ②는 1이 됩니다. 차이는 들어오는 엣지가
> 0인 노드 때문입니다 — ①은 `분리불안(훈련법)`(indeg 0), ②는 `슬개골탈구 예방`과
> `슬개골탈구에 좋은 운동`(각 indeg 1이지만 `감별필요`가 아님). **대조할 값은 경로
> 개수 27 / 19이고, 2026-08-20 재적재 후 실 DB에서 둘 다 일치했습니다.**

오프라인 예측 재실행:

```powershell
uv run python scripts/preview_queries.py
```

## 6. 그 다음

①②에서 경로가 나오면 **Neo4j Browser 화면 캡처**를 준비합니다 (데모 시나리오 ③
의료 감별 경로가 ②입니다 — `docs/demo_scenarios.md` 참고).

미해결로 남겨둔 것:

- **`금기` 엣지가 1개뿐입니다.** 데모 시나리오 ④(처방 거절)가 이 엣지에 기대고
  있다면 지금 개수로는 부족합니다.
- **엔티티 해소가 alias 3건에서 멈춰 있습니다.** 다음 후보는 표면형 중복 상위권
  (`data/graph/stage2_summary.md`의 중복 목록). 통합 여부는 사람이 판단하기로 한
  사항이라 임의로 늘리지 않았습니다.
- **`원칙` 16개** — v2 프롬프트가 훈련법 추출을 막자 일부가 `원칙`으로 재분류됐습니다.
  스키마상 `원칙`은 훈련법과 같은 엣지 권한을 가집니다. 전체의 4.4%라 필터 없이
  진행하기로 했지만, 그래프에서 이상하게 보이면 여기가 원인입니다.
