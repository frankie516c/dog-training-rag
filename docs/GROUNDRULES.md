# 그라운드룰 (RAG·비서 파트)

팀에서 정한 규칙. 개인 취향으로 뒤집지 말 것.

| 항목 | 규칙 | 비고 |
|---|---|---|
| 패키지 관리 | **uv** | `pip install` 직접 금지. 속도가 이유 |
| 백엔드 | **FastAPI** | 고정 |
| 프론트엔드 | **Next.js** | 화면 구성은 자유 |
| 모델 | 자유 (local / API 무관) | 아래 선택 근거 참고 |
| DB | **각자 사용** | 서브PC 적재 시 병목 우려로 공용 DB를 쓰지 않음 |
| ERD | **우선 배제** | 목적이 RAG 경험이라 스키마 설계에 시간 쓰지 않음 |
| GitHub | SAJOYO org에 **각자 레포**를 파서 test 작업 | 이 저장소가 그것 |

## 이 저장소의 선택과 근거

규칙이 자유를 준 항목(모델·DB·화면)에 대해 내린 결정입니다. 이 PC 환경에 맞춘 것이라 다른 팀원과 달라도 정상입니다.

### 실측된 제약

```
GPU      : RTX 3050 / VRAM 6 GB
Node     : v24.18.0
Python   : 3.14.6 (uv 관리)
Docker   : Docker Desktop 4.86.0 설치
ffmpeg   : 없음 — 이 파이프라인에는 필요 없음 (아래 참고)
```

### DB — Qdrant 임베디드 모드

`QdrantClient(path="./data/qdrant")`로 **서버 없이 로컬 파일**로 굴립니다.

- Docker가 없는데, 벡터 DB 하나 때문에 Docker Desktop(WSL2 포함)을 까는 건 과합니다
- "각자 사용" 규칙과 맞습니다 — 공용 서버가 없으니 병목도 없습니다
- 나중에 서버 모드로 옮길 때 `path=` 를 `url=` 로 바꾸는 정도라 이전 비용이 낮습니다
- ERD를 배제한 규칙과도 맞습니다. 관계형 스키마 설계 없이 컬렉션 하나로 시작합니다

### 임베딩 — 로컬

한국어 검색 품질이 핵심이라 한국어에 강한 모델을 로컬로 돌립니다. `BAAI/bge-m3` 계열, 한국어 특화가 필요하면 `nlpai-lab/KURE-v1`. fp16 기준 VRAM 2GB 미만이라 6GB에 여유롭게 들어갑니다.

임베딩을 로컬로 두는 이유는 비용이 아니라 **반복 실험** 때문입니다. 청킹 전략을 바꿀 때마다 3천 개 청크를 다시 임베딩해야 하는데, API로는 시도 횟수가 줄어듭니다.

### 생성 — API

**로컬 LLM을 쓰지 않습니다.** VRAM 6GB로는 4bit 양자화 7B급이 한계인데, 한국어 생성 품질이 데모에서 티가 납니다. 검색이 잘 돼도 답변이 어색하면 RAG를 평가할 수 없습니다.

임베딩(로컬) + 생성(API) 하이브리드가 이 하드웨어에서 합리적입니다.

### 전사 — faster-whisper, int8_float16

`large-v3`를 fp16으로 올리면 약 4.7GB로 6GB에 빠듯합니다. `int8_float16`으로 낮춰 여유를 둡니다.

**시스템 `ffmpeg`는 설치하지 않습니다.** 처음에 필요하다고 적었으나 실측 결과 아니었습니다.

- 오디오는 `-f bestaudio`로 원본 스트림(opus/webm)을 그대로 받습니다 — 후처리가 없으니 yt-dlp에 ffmpeg가 필요 없습니다
- faster-whisper 1.x는 **PyAV로 디코딩**하고, PyAV는 ffmpeg 라이브러리를 휠에 내장합니다
- 실제로 시스템 ffmpeg 없이 48kHz opus → 16kHz mono 디코딩이 되는 것을 확인했습니다

ffmpeg가 필요해지는 경우는 `--extract-audio --audio-format wav`처럼 **포맷 변환을 시킬 때**입니다. 그럴 이유가 없습니다 — Whisper는 어차피 16kHz로 리샘플하므로 중간에 wav를 만드는 건 디스크만 낭비합니다.

## 배제한 것

- **ERD·관계형 스키마 설계** — 규칙대로 배제. 메타데이터는 벡터 DB의 payload에 넣습니다
- **공용 DB 서버** — 규칙대로 배제
- **시스템 ffmpeg** — 불필요함을 확인
- **로컬 생성 LLM** — VRAM 6GB 제약

## Docker

Docker Desktop 4.86.0 + CLI 29.7.2 설치됨. 이 저장소의 벡터 DB는 **임베디드 모드라 Docker를 쓰지 않습니다.** 나중에 Qdrant를 서버로 띄우거나 팀 공통 실행 환경이 필요해지면 그때 씁니다.

### 이 PC에서 Docker를 처음 띄울 때 걸린 것

Docker Desktop이 `virtualisation support wasn't detected`로 실행에 실패했습니다. **BIOS 문제가 아닙니다.**

```
VirtualizationFirmwareEnabled : True    ← BIOS의 VT-x는 켜져 있음
SecondLevelAddressTranslation : True
VMMonitorModeExtensions       : True
HyperVisorPresent             : False   ← Windows 가상화 기능이 꺼져 있음
```

메시지가 BIOS를 가리키는 것처럼 읽히지만 실제 원인은 Windows 선택적 기능입니다. 관리자 권한으로:

```powershell
wsl --install --no-distribution
```

`--no-distribution`을 붙이는 건 Docker Desktop이 자체 WSL 배포판(`docker-desktop`)을 만들기 때문입니다. Ubuntu 같은 걸 따로 깔 필요가 없습니다. 실행 후 **재부팅**해야 적용됩니다.
