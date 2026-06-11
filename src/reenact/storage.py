"""Load/save recordings from/to JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from reenact.migrations import migrate
from reenact.schema import Recording


def save(recording: Recording, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{recording.name}.json"
    path.write_text(recording.model_dump_json(indent=2), encoding="utf-8")
    return path


def load(name: str, directory: Path) -> Recording:
    p = Path(name)
    path = p if p.is_absolute() else directory / p.with_suffix(".json")
    if not path.exists():
        raise FileNotFoundError(f"Recording not found: {path}")
    raw: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    raw = migrate(raw)
    return Recording.model_validate(raw)


def list_recordings(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))
