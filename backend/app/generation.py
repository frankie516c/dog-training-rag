from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from backend.app.domain import ContentLanguage

# A fence that opens on the first line and closes on the last one, wrapping everything.
_WRAPPING_CODE_FENCE = re.compile(
    r"\A```[^\n`]*\n?(?P<body>.*?)\n?```\Z",
    re.DOTALL,
)


class GenerationError(RuntimeError):
    """A provider failed without exposing credentials or provider response bodies."""


@dataclass(frozen=True)
class GenerationEvidence:
    claim: str
    topic: str
    limitations: tuple[str, ...]


class GenerationProvider(Protocol):
    async def generate(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        evidence: tuple[GenerationEvidence, ...],
    ) -> str: ...


def build_generation_messages(
    *,
    message: str,
    response_language: ContentLanguage,
    evidence: tuple[GenerationEvidence, ...],
) -> list[dict[str, str]]:
    """Build a grounded prompt containing no source metadata or original text."""

    evidence_payload = [
        {
            "claim": item.claim,
            "topic": item.topic,
            "limitations": list(item.limitations),
        }
        for item in evidence
    ]
    system_message = (
        "Answer only from the supplied, human-approved evidence. "
        "Do not invent steps, procedures, or facts beyond that evidence. "
        "Do not newly recommend punishment-based or fear-based methods. "
        "Preserve every stated limitation. "
        f"Write the answer in language code {response_language.value}. "
        "Reply with plain prose only. "
        "Do not wrap the reply in a JSON object, a Markdown code fence, or YAML. "
        "Do not emit field names or a response schema such as answer, citations, or "
        "limitations. "
        "The server assembles citations and limitations separately, so do not write them."
    )
    user_message = "\n".join(
        (
            f"Question: {message}",
            "Evidence:",
            json.dumps(evidence_payload, ensure_ascii=False, separators=(",", ":")),
        )
    )
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def normalize_generated_answer(content: str) -> str:
    """Undo whole-response JSON or code-fence wrapping from a local model.

    Deliberately narrow. It only unwraps when the *entire* response is one wrapper, so
    prose that merely mentions JSON or contains an inline fence is returned untouched.
    An empty result is left empty for the caller to reject through the existing
    generation failure path.
    """

    text = content.strip()

    fence = _WRAPPING_CODE_FENCE.match(text)
    if fence is not None and "```" not in fence.group("body"):
        text = fence.group("body").strip()

    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
        except ValueError:
            return text
        if isinstance(payload, dict) and isinstance(payload.get("answer"), str):
            return payload["answer"].strip()

    return text


class OpenAICompatibleGenerationProvider:
    """Minimal adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        normalized_model = model.strip()
        parsed_url = httpx.URL(normalized_base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
            raise ValueError("generation base URL must be an absolute HTTP(S) URL")
        if not normalized_model:
            raise ValueError("generation model must not be empty")
        self._endpoint = f"{normalized_base_url}/chat/completions"
        self._model = normalized_model
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._timeout_seconds = timeout_seconds

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Return the raw assistant content for a caller-built message list.

        Unlike `generate()` this applies no normalization, because the grounded path
        expects a structured payload and must parse it itself.
        """

        body = await self._post({"model": self._model, "messages": messages, "stream": False})
        content = (body["choices"][0]["message"] or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise GenerationError("generation provider returned an empty completion")
        return content

    async def generate(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        evidence: tuple[GenerationEvidence, ...],
    ) -> str:
        payload = {
            "model": self._model,
            "messages": build_generation_messages(
                message=message,
                response_language=response_language,
                evidence=evidence,
            ),
            "stream": False,
        }
        try:
            body = await self._post(payload)
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise GenerationError("generation provider returned an empty answer")
            answer = normalize_generated_answer(content)
            if not answer:
                raise GenerationError("generation provider returned an empty answer")
            return answer
        except GenerationError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationError("generation provider request failed") from exc

    async def _post(self, payload: dict[str, object]) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(self._endpoint, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise GenerationError("generation provider request failed") from exc
