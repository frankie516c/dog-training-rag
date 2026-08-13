"""Provenance helpers: endpoint sanitisation, response fingerprints, repo state.

Three problems this solves, each found by review of the v0 harness:

* a raw ``base_url`` was written into four artifacts, and gateway URLs can carry
  credentials in userinfo, query or path;
* semantic labels were keyed by ``(question_id, version, run)`` alone, so re-running the
  evaluation silently re-attached judgements written for different text;
* the manifest hashed only a few harness files, omitting the evidence JSONL that actually
  determines every prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_CREDENTIAL_LIKE = re.compile(r"(sk-|key|token|secret|password|bearer)", re.IGNORECASE)


def sanitize_endpoint(base_url: str) -> dict[str, str | bool]:
    """Reduce a provider URL to the minimum needed to reproduce a run.

    Everything that can carry a secret is dropped: userinfo, query, fragment, and the path
    whenever it looks credential-bearing. Only scheme, host and port survive.
    """

    parts = urlsplit(base_url.strip())
    host = (parts.hostname or "").lower()
    origin = f"{parts.scheme}://{host}" if host else ""
    if parts.port:
        origin = f"{origin}:{parts.port}"

    path = parts.path or ""
    path_is_suspicious = bool(_CREDENTIAL_LIKE.search(path)) or len(path.strip("/")) > 24
    return {
        "provider_type": "openai_compatible",
        "locality": "local" if host in LOCAL_HOSTS else "remote",
        "sanitized_origin": origin,
        "path_label": "" if path_is_suspicious else path,
        "had_userinfo": bool(parts.username or parts.password),
        "had_query_or_fragment": bool(parts.query or parts.fragment),
    }


def sanitize_config(config: dict) -> dict:
    """Strip a raw ``base_url`` from any config before it reaches an artifact.

    The legacy v0 records carry their config inline with the URL in full. Copying that
    dict into a manifest or a summary re-exported the raw URL, which is the leak the
    sanitiser exists to prevent — so every writer passes the config through here.
    """

    cleaned = dict(config)
    raw = cleaned.pop("base_url", None)
    if raw is not None and "endpoint" not in cleaned:
        cleaned["endpoint"] = sanitize_endpoint(raw)
        cleaned["endpoint_recovered_from_legacy_base_url"] = True
    return cleaned


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def response_fingerprint(record: dict) -> str:
    """Bind a semantic judgement to the exact response it was written about.

    Any change to the question, the fixed context, the raw provider output, the parsed
    answer, the answerable verdict, the used card ids or the prompt version produces a
    different fingerprint, so a stale label can never be re-applied.
    """

    payload = {
        "prompt_version": record.get("prompt_version"),
        "message": record.get("message"),
        "card_ids": record.get("card_ids"),
        "raw_response": record.get("raw_response"),
        "answer": record.get("answer"),
        "answerable": record.get("provider_result") == "accepted",
        "used_card_ids": record.get("used_card_ids"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_state(repo_root: Path) -> dict[str, str | bool | None]:
    """Commit SHA and whether the tree was dirty. Absence is recorded, not invented."""

    def run(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout.strip() if completed.returncode == 0 else None

    head = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {
        "commit": head,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_working_tree": bool(status) if status is not None else None,
    }
