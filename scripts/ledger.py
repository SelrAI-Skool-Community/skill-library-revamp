#!/usr/bin/env python3
"""Shared JSON-ledger helpers for the skill-library revamp pipeline."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA: dict[str, Any] = {
    "skill": "",
    "path": "",
    "sha_before": None,
    "sha_after": None,
    "flags": {},
    "grade": None,
    "tier": None,
    "tier_source": None,
    "stages": {},
    "verify": {},
    "patterns_emitted": [],
}


def utc_iso() -> str:
    """Return a compact UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stage_done(obj: dict[str, Any], stage: str) -> None:
    """Mark one pipeline stage complete without touching other stage records."""
    obj.setdefault("stages", {})[stage] = {"status": "done", "ts": utc_iso()}


def _ledger_dir(run_dir: str | Path) -> Path:
    return Path(run_dir).expanduser() / "ledger"


def _skill_name(skill: str | Path) -> str:
    name = Path(str(skill)).name
    if not name or name.startswith("_") or name in {".", ".."}:
        raise ValueError(f"invalid ledger skill name: {skill!r}")
    return name


def _with_schema(obj: dict[str, Any]) -> dict[str, Any]:
    merged = {
        key: value.copy() if isinstance(value, dict) else list(value)
        if isinstance(value, list)
        else value
        for key, value in SCHEMA.items()
    }
    merged.update(obj)
    for key in ("flags", "stages", "verify"):
        if not isinstance(merged[key], dict):
            raise ValueError(f"ledger field {key!r} must be an object")
    if not isinstance(merged["patterns_emitted"], list):
        raise ValueError("ledger field 'patterns_emitted' must be a list")
    return merged


def load(run_dir: str | Path, skill: str | Path) -> dict[str, Any]:
    """Load one skill ledger, returning the complete empty schema if absent."""
    name = _skill_name(skill)
    path = _ledger_dir(run_dir) / f"{name}.json"
    if not path.exists():
        obj = _with_schema({})
        obj["skill"] = name
        return obj
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"ledger is not a JSON object: {path}")
    obj = _with_schema(raw)
    if obj["skill"] not in {"", name}:
        raise ValueError(
            f"ledger skill mismatch in {path}: {obj['skill']!r} != {name!r}"
        )
    obj["skill"] = name
    return obj


def atomic_write_json(path: str | Path, obj: Any) -> None:
    """Write JSON atomically using a temporary file in the destination directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(obj, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def atomic_write_text(path: str | Path, text: str) -> None:
    """Write UTF-8 text atomically in the destination directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def save(run_dir: str | Path, skill: str | Path, obj: dict[str, Any]) -> None:
    """Atomically save one skill ledger at <run-dir>/ledger/<dirname>.json."""
    name = _skill_name(skill)
    complete = _with_schema(obj)
    complete["skill"] = name
    atomic_write_json(_ledger_dir(run_dir) / f"{name}.json", complete)


def all_skills(run_dir: str | Path) -> Iterator[dict[str, Any]]:
    """Yield every skill ledger in dirname order, excluding control JSON files."""
    ledger_dir = _ledger_dir(run_dir)
    if not ledger_dir.is_dir():
        raise FileNotFoundError(f"ledger directory not found: {ledger_dir}")
    for path in sorted(ledger_dir.glob("*.json"), key=lambda item: item.name):
        if path.name.startswith("_"):
            continue
        yield load(run_dir, path.stem)
