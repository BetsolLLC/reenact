"""Runtime configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_RECORDINGS_DIR = Path.home() / ".reenact" / "recordings"


class Config:
    def __init__(
        self,
        recordings_dir: Path = DEFAULT_RECORDINGS_DIR,
        headed: bool = False,
    ) -> None:
        self.recordings_dir = recordings_dir
        self.headed = headed
