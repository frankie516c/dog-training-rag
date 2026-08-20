"""Measure classify_input (v1) and classify_input_v2 (v2 + whitelist) on the
same two fixed sets, side by side.

    - data/eval/queries/out_of_corpus_queries.json (14 questions, "범위 밖"):
      block rate. These are corpus-scope negatives, not all of them medical —
      neither version is expected to catch all 14, and this script does not
      pretend either will. It reports how many each actually catches.

    - data/eval/queries/owner_fixtures.jsonl (20 questions, 견주 픽스처):
      false-positive rate. Every one of these is a real training question a
      human already reviewed (review_status APPROVED/PENDING); a guardrail
      that mislabels them MEDICAL is blocking questions it should answer.
      This number matters more than the block rate above — a lexicon that
      blocks everything scores perfectly on the first set and destroys the
      second.

Q17 and Q19 are reported individually because they are the two owner fixtures
labeled with a semantic refusal reason instead of a retrieval gap
(refuse_reason MEDICAL and SCOPE respectively). Q17 is the case this guardrail
exists for. Q19 is a cat-behavior question — out of this guardrail's remit by
design — and neither version should mark it MEDICAL; its REFUSE comes from
scope, not medicine.

v1 (frozen/frozen_stage2_0820.jsonl entity dump) is kept and re-measured here
rather than deleted, because its failure is the documented reason v2 exists:
v1's vocabulary is drawn from what the training-video corpus itself discusses,
which is backwards for a guardrail whose job is to catch medical questions the
corpus has nothing to do with. See build_report()'s "왜 v1이 실패했는가" section.

Neither medical_terms_v2.json nor training_whitelist_v1.json is adjusted by
this script based on what it finds. Both went through the human review the
user asked for and are marked status "confirmed" as of 2026-08-20. If the
numbers below suggest a term should still be added or dropped, that is
reported, not acted on here.

OUT_OF_CORPUS_MEDICAL_TOPIC below is a human judgment call, made *after* v1/v2
results were already known, about which of the 14 out-of-corpus questions are
actually medical in nature (as opposed to scope/logistics questions that
happen to be unanswerable from this corpus). It is reported for transparency
next to the block-rate table, not as independent ground truth — that it lines
up with what v2 catches should be read as "consistent with", not "blind
confirmation of", v2's block list.

Usage:
    uv run python scripts/evaluate_medical_guardrail.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

DEFAULT_OUT_OF_CORPUS = Path("data/eval/queries/out_of_corpus_queries.json")
DEFAULT_OWNER_FIXTURES = Path("data/eval/queries/owner_fixtures.jsonl")
DEFAULT_REPORT = Path("reports/medical_guardrail_v1v2_comparison.md")

FLAGGED_FIXTURE_IDS = ("Q17", "Q19")

# Human judgment: is this out-of-corpus question actually medical (asks about
# diagnosis/treatment/medication/emergency care), or a scope/logistics question
# that merely has no answer in this corpus? Made after seeing v1/v2 results —
# see the module docstring's caveat on how to read this next to the block-rate
# table. Borderline calls (n007, n008, n010) are explained where this is used.
OUT_OF_CORPUS_MEDICAL_TOPIC = {
    "n001": (False, "배변 실수 사후 대처 — 훈련/관리 문제, 진단·처치 요청 아님"),
    "n002": (False, "배변 실수 관리 — 위와 동일"),
    "n003": (False, "사료 급여량 — 영양 계량 문제, 질환·처치 아님"),
    "n004": (True, "종합백신 접종 스케줄 — 의료 처치(접종) 그 자체"),
    "n005": (True, "중성화 수술 시기·부작용 — 수술 및 그 영향에 대한 질문"),
    "n006": (False, "목욕 주기 — 미용 관리, 의료 아님"),
    "n007": (False, "양치·치석 관리 — 예방 위생 루틴을 묻는 것이지 치료·진단 요청 아님(경계 사례)"),
    "n008": (False, "노령견 계단 회피, 환경을 어떻게 바꿀지 — 생활 환경 조정 질문. 관절 문제를 "
                     "암시할 수 있으나 진단·처치를 요청하지 않음(경계 사례)"),
    "n009": (True, "멀미약 투약 여부 — 투약 판단을 직접 요청"),
    "n010": (False, "산책 시간대 안전성 — 예방·타이밍 질문이지 치료 요청 아님(경계 사례)"),
    "n011": (False, "합사 시작 방법 — 다견 가정 관계 문제, 의료 아님"),
    "n012": (False, "펫보험 — 제도·비용 문제, 의료 아님"),
    "n013": (False, "위탁 방식 선택 — 돌봄 로지스틱스, 의료 아님"),
    "n014": (True, "이물 섭취(초코볼) 후 응급 여부 — 응급 처치 판단을 직접 요청"),
}


class GuardrailEvalError(RuntimeError):
    """Raised when a query set or a lexicon is unusable."""


def _load_module(name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise GuardrailEvalError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guardrail = _load_module("medical_guardrail")


def load_out_of_corpus(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise GuardrailEvalError(f"file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload.get("queries")
    if not isinstance(queries, list) or not queries:
        raise GuardrailEvalError(f"{path}: 'queries' must be a non-empty array")
    return queries


def load_owner_fixtures(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise GuardrailEvalError(f"file not found: {path}")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise GuardrailEvalError(f"invalid JSON at {path}:{number}") from exc
    if not rows:
        raise GuardrailEvalError(f"empty fixture set: {path}")
    return rows


def evaluate(
    out_of_corpus: Sequence[dict[str, Any]],
    owner_fixtures: Sequence[dict[str, Any]],
    classify: Callable[[str], Any],
) -> dict[str, Any]:
    """Run one classifier over both sets. `classify(question) -> InputVerdict`."""
    ooc_results = [
        {"query_id": r["query_id"], "question": r["question"], "topic": r.get("topic"),
         "verdict": classify(str(r["question"]))}
        for r in out_of_corpus
    ]
    fixture_results = [
        {
            "query_id": r["query_id"], "question": r["question"],
            "expected_outcome": r.get("expected_outcome"),
            "refuse_reason": r.get("refuse_reason"), "guard_level": r.get("guard_level"),
            "verdict": classify(str(r["question"])),
        }
        for r in owner_fixtures
    ]
    blocked = [r for r in ooc_results if r["verdict"].is_medical]
    # A fixture's refuse_reason of "MEDICAL" means the guardrail is *supposed* to
    # catch it (Q17, Q18) — that is a correct block, not a false positive. Only a
    # MEDICAL verdict on a fixture whose refuse_reason is something else (GAP,
    # SCOPE, or none) is a normal training question wrongly blocked.
    false_positives = [
        r for r in fixture_results
        if r["verdict"].is_medical and r["refuse_reason"] != "MEDICAL"
    ]
    true_positives = [
        r for r in fixture_results
        if r["verdict"].is_medical and r["refuse_reason"] == "MEDICAL"
    ]
    flagged = {
        query_id: next((r for r in fixture_results if r["query_id"] == query_id), None)
        for query_id in FLAGGED_FIXTURE_IDS
    }
    return {
        "out_of_corpus": ooc_results,
        "owner_fixtures": fixture_results,
        "block_count": len(blocked),
        "block_total": len(ooc_results),
        "blocked_ids": [r["query_id"] for r in blocked],
        "false_positive_count": len(false_positives),
        "false_positive_total": len(fixture_results),
        "false_positive_ids": [r["query_id"] for r in false_positives],
        "true_positive_ids": [r["query_id"] for r in true_positives],
        "flagged": flagged,
    }


def _verdict_cell(verdict: Any) -> str:
    if verdict.whitelist_matched:
        return "PASS (whitelist: " + ", ".join(verdict.whitelist_matched) + ")"
    if not verdict.is_medical:
        return "PASS"
    return "MEDICAL (" + ", ".join(verdict.matched_terms) + ")"


def _short(verdict: Any) -> str:
    if verdict.is_medical:
        return "MEDICAL"
    return "PASS(wl)" if verdict.whitelist_matched else "PASS"


def build_report(
    v1: dict[str, Any], v2: dict[str, Any],
    v1_terms: Sequence[str], v2_terms: Sequence[str], whitelist_terms: Sequence[str],
) -> str:
    lines: list[str] = []
    lines.append("# 의료 가드레일 v1 vs v2 — 비교 검증 리포트")
    lines.append("")
    lines.append(
        "`scripts/evaluate_medical_guardrail.py`가 생성합니다. 직접 편집하지 마세요. "
        "재실행하려면 `uv run python scripts/evaluate_medical_guardrail.py`."
    )
    lines.append("")
    lines.append(
        f"- v1 사전: `data/guardrail/medical_terms_v1.json` (용어 {len(v1_terms)}개, "
        "`frozen/frozen_stage2_0820.jsonl`의 질환·증상 엔티티 덤프)"
    )
    lines.append(
        f"- v2 사전: `data/guardrail/medical_terms_v2.json` (용어 {len(v2_terms)}개, "
        "손수 작성한 코퍼스 밖 일반 수의 어휘) — **confirmed (2026-08-20)**"
    )
    lines.append(
        f"- 훈련 화이트리스트: `data/guardrail/training_whitelist_v1.json` (용어 "
        f"{len(whitelist_terms)}개, v2보다 매칭 우선순위 높음) — **confirmed (2026-08-20)**"
    )
    lines.append("")
    lines.append(
        "> **처리 이력**: 원래 목록의 '약'(한 음절)은 v1과 공유하는 로더의 "
        "`MIN_TERM_CHARS=2` 필터에 걸려 조용히 매칭에서 빠지고 있었다. 사용자에게 "
        "보여준 뒤 '약을 먹여'라는 2글자 이상 구절로 교체하기로 결정했다(2026-08-20) "
        "— `data/guardrail/medical_terms_v2.json`의 risk_notes에 트레이드오프를 "
        "적어 뒀다. v2 사전과 화이트리스트 모두 이 교체를 반영한 상태로 "
        "2026-08-20에 confirmed로 확정됐다."
    )
    lines.append("")

    lines.append("## 왜 v1이 실패했는가")
    lines.append("")
    lines.append(
        "v1의 소스(`frozen/frozen_stage2_0820.jsonl`)는 훈련 영상 코퍼스 자체를 추출한 "
        "결과다. 이 가드레일이 막아야 하는 대상은 **코퍼스에 없는** 의료 질문인데, "
        "코퍼스 안에 있는 병명·증상 어휘로 그 사전을 만든 것이 방향이 거꾸로였다. "
        "구체적으로 두 방향의 실패가 났다:"
    )
    lines.append("")
    lines.append(
        "1. **재현율 실패(Q17을 못 잡음)** — v1 용어는 코퍼스 청크에서 실제로 등장한 "
        "구체 병명·증상 표현(\"슬개골 탈구\", \"외이도염\")이라, 코퍼스에 없는 일반 "
        "의료 상황(Q17: \"아토피 피부염\", \"약용 샴푸\", \"처방식 사료\")과 문자열이 "
        "겹치지 않았다."
    )
    lines.append(
        "2. **정밀도 실패(오탐 6/20)** — 그래프 추출이 훈련 영상 전사문을 대상으로 "
        "\"증상\" 타입을 매긴 결과, 짖음·불안·분리불안·하울링처럼 **문제행동 설명과 "
        "증상 설명이 겹치는** 훈련 도메인 일상어까지 사전에 들어갔다. 이 단어들은 "
        "코퍼스가 다루는 정상적인 훈련 상담 주제이지 의료 신호가 아니다."
    )
    lines.append(
        "- v2는 두 실패 모두 구조적으로 고친다: 어휘를 코퍼스 추출이 아니라 손으로 "
        "고른 일반 수의 어휘로 바꿔 (1)을 겨냥하고, 훈련 도메인 화이트리스트를 "
        "사전보다 우선하게 두어 (2)를 겨냥한다."
    )
    lines.append("")

    medical_topic_ids = [qid for qid, (is_med, _) in OUT_OF_CORPUS_MEDICAL_TOPIC.items() if is_med]
    lines.append("## 범위 밖 14건 — 차단률 (v1 vs v2)")
    lines.append("")
    lines.append(
        f"v1 **{v1['block_count']}/{v1['block_total']}건** → "
        f"v2 **{v2['block_count']}/{v2['block_total']}건**. "
        "이 14건은 '코퍼스에 답이 없다'는 근거로 골라진 집합이지 전부 의료 질문은 "
        f"아니다 — 사람이 판정한 의료 성격 질문은 **{len(medical_topic_ids)}/14건**"
        f"({', '.join(medical_topic_ids)})이며, 둘 다 14/14를 목표로 하지 않는다. "
        "이 판정은 v1/v2 결과를 이미 본 뒤 내린 것이라(모듈 docstring 참고) "
        "v2의 차단 목록과 일치하는 것을 독립적 검증으로 읽지 말 것."
    )
    lines.append("")
    lines.append("| id | 의료 성격(사람 판정) | topic | 질문 | v1 | v2 |")
    lines.append("|---|---|---|---|---|---|")
    v2_ooc_by_id = {r["query_id"]: r for r in v2["out_of_corpus"]}
    for row in v1["out_of_corpus"]:
        v2_row = v2_ooc_by_id[row["query_id"]]
        is_medical_topic, _reason = OUT_OF_CORPUS_MEDICAL_TOPIC[row["query_id"]]
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            row["query_id"], "예" if is_medical_topic else "아니오",
            row["topic"] or "-", row["question"],
            _verdict_cell(row["verdict"]), _verdict_cell(v2_row["verdict"])
        ))
    lines.append("")
    lines.append("판정 근거 (경계 사례는 표시):")
    for query_id, (is_medical_topic, reason) in OUT_OF_CORPUS_MEDICAL_TOPIC.items():
        lines.append(f"- {query_id} ({'예' if is_medical_topic else '아니오'}): {reason}")
    lines.append("")

    lines.append("## 견주 픽스처 20건 — 오탐률 (v1 vs v2)")
    lines.append("")
    lines.append(
        f"v1 **{v1['false_positive_count']}/{v1['false_positive_total']}건 오탐** → "
        f"v2 **{v2['false_positive_count']}/{v2['false_positive_total']}건 오탐**. "
        "(오탐 = MEDICAL로 막혔는데 refuse_reason이 MEDICAL이 아닌 건 — 정상 훈련 "
        "질문을 잘못 막은 경우만 센다. Q17·Q18처럼 refuse_reason이 원래 MEDICAL인 "
        "질문이 MEDICAL로 잡히는 것은 오탐이 아니라 이 가드레일이 의도한 정탐이다.)"
    )
    if v2["true_positive_ids"]:
        lines.append(
            f"- v2 정탐(의도한 MEDICAL 차단): {', '.join(v2['true_positive_ids'])}"
        )
    lines.append("")
    lines.append("| id | 기대 | refuse_reason | 질문 | v1 | v2 |")
    lines.append("|---|---|---|---|---|---|")
    v2_fixture_by_id = {r["query_id"]: r for r in v2["owner_fixtures"]}
    for row in v1["owner_fixtures"]:
        v2_row = v2_fixture_by_id[row["query_id"]]
        mark = " ⚠" if row["query_id"] in FLAGGED_FIXTURE_IDS else ""
        lines.append("| {}{} | {} | {} | {} | {} | {} |".format(
            row["query_id"], mark, row["expected_outcome"], row["refuse_reason"] or "-",
            row["question"], _verdict_cell(row["verdict"]), _verdict_cell(v2_row["verdict"])
        ))
    lines.append("")
    lines.append(
        "**Q16(v2 남은 오탐 1건)**: 과거형 서술과 요청을 문자열로 구분 불가 — "
        "문자열 매칭 가드레일의 구조적 한계. \"진단을 받은\"(과거 서술, 행동 신호를 "
        "묻는 질문)과 \"진단해 주세요\"(요청)는 같은 단어 \"진단\"을 포함하지만 "
        "의도가 반대인데, 부분 문자열 매칭은 문장 안의 시제·화행을 구분하지 못한다. "
        "화이트리스트로도 못 잡는 유형이며, 안건으로는 "
        "[`docs/agenda_0825.md`](../docs/agenda_0825.md) 7번(가드레일 의미 기반 "
        "분류 검토)에 남겼다."
    )
    lines.append("")

    lines.append("## Q17 · Q19 개별 확인 (v1 vs v2)")
    lines.append("")
    lines.append(
        "Q17(refuse_reason MEDICAL)은 이 가드레일이 잡아야 할 목표 사례다. "
        "Q19(refuse_reason SCOPE)는 고양이 행동학 질문이라 이 가드레일의 범위 밖이며, "
        "두 버전 모두 잡지 않아야 한다."
    )
    lines.append("")
    lines.append("| id | refuse_reason | 기대 | v1 판정 | v1 결과 | v2 판정 | v2 결과 |")
    lines.append("|---|---|---|---|---|---|---|")
    expectations = {"Q17": True, "Q19": False}
    for query_id in FLAGGED_FIXTURE_IDS:
        v1_row = v1["flagged"][query_id]
        v2_row = v2["flagged"][query_id]
        expected = expectations[query_id]
        v1_ok = "✓" if v1_row["verdict"].is_medical == expected else "✗"
        v2_ok = "✓" if v2_row["verdict"].is_medical == expected else "✗"
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            query_id, v1_row["refuse_reason"], "MEDICAL" if expected else "PASS",
            _verdict_cell(v1_row["verdict"]), v1_ok,
            _verdict_cell(v2_row["verdict"]), v2_ok,
        ))
    lines.append("")

    lines.append("## 출력 측 판정 (§3, v1/v2 공통)")
    lines.append("")
    lines.append(
        "`medical_guardrail.classify_output`은 이번에도 손대지 않았고, 이 리포트가 재는 "
        "두 세트로는 검증되지 않는다 — 이 저장소의 오프라인 파이프라인에는 실제 LLM "
        "호출이 없어 (`data/eval/generation/*.jsonl`의 답변은 `answer: null` 또는 수기 "
        "dry-run뿐) owner_fixtures 20건에 대한 실제 생성 답변이 없다. "
        "`tests/test_medical_guardrail.py`의 예시 텍스트로만 단위 검증되었다."
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "v2 사전과 화이트리스트는 2026-08-20에 confirmed로 확정됐다. 남은 알려진 "
        "한계(Q16, 경계 사례 n007·n008·n010)는 위에 표시했고, 이 스크립트는 그 결과를 "
        "보고 스스로 항목을 조정하지 않았다."
    )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        v1_terms = guardrail.load_medical_terms(guardrail.DEFAULT_LEXICON_PATH)
        v2_terms = guardrail.load_medical_terms_v2(guardrail.DEFAULT_LEXICON_V2_PATH)
        whitelist_terms = guardrail.load_training_whitelist(guardrail.DEFAULT_WHITELIST_PATH)
        out_of_corpus = load_out_of_corpus(DEFAULT_OUT_OF_CORPUS)
        owner_fixtures = load_owner_fixtures(DEFAULT_OWNER_FIXTURES)
    except (guardrail.GuardrailError, GuardrailEvalError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    v1_result = evaluate(
        out_of_corpus, owner_fixtures,
        lambda q: guardrail.classify_input(q, v1_terms),
    )
    v2_result = evaluate(
        out_of_corpus, owner_fixtures,
        lambda q: guardrail.classify_input_v2(q, v2_terms, whitelist_terms),
    )

    report = build_report(v1_result, v2_result, v1_terms, v2_terms, whitelist_terms)
    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_bytes(report.encode("utf-8"))

    print("범위 밖 14건 차단률")
    print(f"  v1: {v1_result['block_count']}/{v1_result['block_total']} "
          f"({', '.join(v1_result['blocked_ids']) or '없음'})")
    print(f"  v2: {v2_result['block_count']}/{v2_result['block_total']} "
          f"({', '.join(v2_result['blocked_ids']) or '없음'})")
    print("견주 픽스처 20건 오탐률 (refuse_reason=MEDICAL인 정탐 제외)")
    print(f"  v1: {v1_result['false_positive_count']}/{v1_result['false_positive_total']} "
          f"({', '.join(v1_result['false_positive_ids']) or '없음'})")
    print(f"  v2: {v2_result['false_positive_count']}/{v2_result['false_positive_total']} "
          f"({', '.join(v2_result['false_positive_ids']) or '없음'}) "
          f"[정탐: {', '.join(v2_result['true_positive_ids']) or '없음'}]")
    for query_id in FLAGGED_FIXTURE_IDS:
        v1_row = v1_result["flagged"][query_id]
        v2_row = v2_result["flagged"][query_id]
        print(f"  {query_id} ({v1_row['refuse_reason']}): "
              f"v1={_short(v1_row['verdict'])} v2={_short(v2_row['verdict'])}")
    print(f"리포트: {DEFAULT_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
