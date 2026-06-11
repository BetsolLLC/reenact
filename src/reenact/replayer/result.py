"""Replay result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class StepResult:
    step_id: str
    intent: str
    status: Literal["pass", "fail", "skip"]
    step_type: str = ""
    strategy_used: str | None = None
    error: str | None = None
    screenshot: Path | None = None
    duration_ms: int = 0
    extracted_value: str | None = None


@dataclass
class ReplayReport:
    recording_name: str
    status: Literal["pass", "fail"]
    steps: list[StepResult] = field(default_factory=list)
    total_ms: int = 0
    extracted: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if s.status == "fail")

    def first_failure(self) -> StepResult | None:
        return next((s for s in self.steps if s.status == "fail"), None)
