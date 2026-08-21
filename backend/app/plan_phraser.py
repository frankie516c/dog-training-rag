"""The one place a provider is called, and the one place its answer can be refused.

Separate from `plan_phrasing` so the rules stay testable without a network, and separate
from `grounded.py` so the checkpoint 5I-A path — where the model also judged answerability
— is not what gets wired back in.
"""

from __future__ import annotations

import logging
from typing import Protocol

from backend.app.domain import ContentLanguage, EvidenceCard
from backend.app.plan_phrasing import (
    PhrasingResult,
    PhrasingVerdict,
    build_phrasing_messages,
    validate_phrasing,
)
from backend.app.response_plans import ResponsePlan

logger = logging.getLogger(__name__)


class CompletionProvider(Protocol):
    async def complete(
        self, messages: list[dict[str, str]], *, options: dict[str, object] | None = None
    ) -> str: ...


class PlanPhraser:
    """Ask a provider to rephrase a reviewed plan, and return it only if it validates."""

    def __init__(
        self,
        *,
        provider: CompletionProvider,
        reasoning_effort: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 320,
    ) -> None:
        self._provider = provider
        options: dict[str, object] = {"temperature": temperature, "max_tokens": max_tokens}
        if reasoning_effort:
            options["reasoning_effort"] = reasoning_effort
        self._options = options

    async def phrase(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        card: EvidenceCard,
        plan: ResponsePlan,
    ) -> PhrasingResult:
        messages = build_phrasing_messages(
            message=message,
            response_language=response_language,
            card=card,
            plan=plan,
        )
        try:
            raw = await self._provider.complete(messages, options=self._options)
        except Exception as exc:
            # Unreachable, timed out, or misbehaving. The caller shows the reviewed plan,
            # so this is a downgrade in prose, not an error for the reader.
            logger.info(
                "plan phrasing unavailable (%s); using the reviewed plan", type(exc).__name__
            )
            return PhrasingResult(PhrasingVerdict.INVALID, reason=f"provider {type(exc).__name__}")

        result = validate_phrasing(raw, message=message, card=card, plan=plan)
        if not result.accepted:
            logger.info("plan phrasing rejected (%s); using the reviewed plan", result.reason)
        return result
