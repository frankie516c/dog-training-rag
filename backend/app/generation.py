from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from backend.app.domain import ContentLanguage


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
        f"Write the answer in language code {response_language.value}."
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

    async def generate(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        evidence: tuple[GenerationEvidence, ...],
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
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
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(self._endpoint, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise GenerationError("generation provider returned an empty answer")
            return content.strip()
        except GenerationError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationError("generation provider request failed") from exc
