"""Small deterministic term matching shared by the scope router and the safety gate.

No tokenizer, no model, no external dependency. Korean and English terms are matched
with different rules because only the ASCII side has usable word boundaries.
"""

from __future__ import annotations

import re

_ASCII_TERM = re.compile(r"^[a-z][a-z \-']*$")


def normalize(text: str) -> str:
    """Casefold and collapse whitespace so term lists stay readable."""

    return re.sub(r"\s+", " ", text.casefold())


def compile_terms(terms: tuple[str, ...]) -> re.Pattern[str]:
    """Compile a term list into one pattern.

    ASCII terms are anchored at a word start and left open at the end, so `bark` also
    matches `barking` and `adapt` also matches `adaptation`. Hangul terms are matched as
    plain substrings; every Hangul term used by callers is chosen to be safe that way.
    """

    if not terms:
        raise ValueError("compile_terms requires at least one term")
    alternatives = [
        rf"\b{re.escape(term)}" if _ASCII_TERM.match(term) else re.escape(term) for term in terms
    ]
    return re.compile("|".join(alternatives))
