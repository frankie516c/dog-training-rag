"""Read a records file and its generation config, whichever layout it uses.

Two layouts exist and both must keep working:

* legacy — the v0 run put its config on line 1 of the JSONL. That file is frozen and is
  never rewritten, so it is parsed as-is.
* current — the runner writes records only, plus a ``<records>_config.json`` sidecar.

Silently returning an empty config was the bug this module removes: the manifest recorded
``"model": ""`` while still printing ``integrity: OK``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from experiments.prompt_eval_v0.provenance import sanitize_config, sha256_file


class ConfigResolutionError(RuntimeError):
    """The generation config for a records file could not be established."""


@dataclass(frozen=True)
class LoadedRun:
    records: list[dict]
    config: dict
    config_source: str


def sidecar_path(records_path: Path) -> Path:
    return records_path.with_name(records_path.stem + "_config.json")


def load_run(records_path: Path) -> LoadedRun:
    """Load records plus config, failing closed when the config cannot be established."""

    if not records_path.exists():
        raise ConfigResolutionError(f"missing records file: {records_path}")

    inline_config: dict = {}
    records: list[dict] = []
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if "prompt_version" in payload:
            records.append(payload)
        elif "config" in payload:
            inline_config = payload["config"]

    sidecar = sidecar_path(records_path)
    if sidecar.exists():
        config = json.loads(sidecar.read_text(encoding="utf-8"))
        source = "sidecar"
        # A sidecar without the binding could be paired with any records file, which is
        # the guarantee this check exists to provide. Absence is a failure, not a pass.
        recorded = config.get("records_sha256")
        if not recorded:
            raise ConfigResolutionError(
                f"{sidecar.name} has no records_sha256; it cannot be bound to a records file"
            )
        if recorded != sha256_file(records_path):
            raise ConfigResolutionError(f"{sidecar.name} was written for a different records file")
    elif inline_config:
        config = inline_config
        source = "legacy_inline"
    else:
        raise ConfigResolutionError(
            f"no config for {records_path.name}: expected {sidecar.name} or a legacy first line"
        )

    if not config.get("model"):
        raise ConfigResolutionError(f"config from {source} has no model recorded")
    # Sanitised at the boundary so no downstream writer can re-export a raw URL.
    return LoadedRun(records=records, config=sanitize_config(config), config_source=source)
