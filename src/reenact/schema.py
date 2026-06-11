"""Reenact workflow schema — Pydantic v2 models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StepType(StrEnum):
    navigate = "navigate"
    click = "click"
    input = "input"
    select = "select"
    key = "key"
    wait = "wait"
    assert_ = "assert"
    scroll = "scroll"
    hover = "hover"
    extract = "extract"


class WaitStrategy(StrEnum):
    actionable = "actionable"
    navigation = "navigation"
    networkidle = "networkidle"
    fixed = "fixed"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class Viewport(BaseModel):
    width: int = 1280
    height: int = 800


class Variable(BaseModel):
    name: str
    default: str | None = None
    secret: bool = False


class RoleSelector(BaseModel):
    """ARIA role + accessible name pair."""

    role: str
    name: str


class SelectorBundle(BaseModel):
    """All selector strategies captured at record time.

    Priority at replay: testid → role → text → css → xpath.
    First strategy yielding exactly one visible match wins.
    """

    testid: str | None = None
    role: RoleSelector | None = None
    text: str | None = None
    css: str | None = None
    xpath: str | None = None
    # Optional frame / shadow-host path for resolver descent
    frame_path: list[str] = Field(default_factory=list)

    def has_any(self) -> bool:
        return any([self.testid, self.role, self.text, self.css, self.xpath])


class WaitConfig(BaseModel):
    strategy: WaitStrategy = WaitStrategy.actionable
    timeout_ms: int = 5000


# ---------------------------------------------------------------------------
# Step models (discriminated union on `type`)
# ---------------------------------------------------------------------------


class NavigateStep(BaseModel):
    id: str
    type: Literal[StepType.navigate] = StepType.navigate
    url: str
    intent: str


class ClickStep(BaseModel):
    id: str
    type: Literal[StepType.click] = StepType.click
    selectors: SelectorBundle
    intent: str
    wait: WaitConfig = Field(default_factory=WaitConfig)


class InputStep(BaseModel):
    id: str
    type: Literal[StepType.input] = StepType.input
    selectors: SelectorBundle
    value: str
    intent: str
    clear_first: bool = True
    wait: WaitConfig = Field(default_factory=WaitConfig)


class SelectStep(BaseModel):
    id: str
    type: Literal[StepType.select] = StepType.select
    selectors: SelectorBundle
    value: str
    selected_label: str | None = None
    selected_index: int | None = None
    intent: str
    wait: WaitConfig = Field(default_factory=WaitConfig)


class KeyStep(BaseModel):
    id: str
    type: Literal[StepType.key] = StepType.key
    key: str
    selectors: SelectorBundle | None = None
    intent: str
    wait: WaitConfig = Field(default_factory=WaitConfig)


class WaitStep(BaseModel):
    id: str
    type: Literal[StepType.wait] = StepType.wait
    strategy: WaitStrategy = WaitStrategy.actionable
    duration_ms: int | None = None
    intent: str


class AssertStep(BaseModel):
    id: str
    type: Literal[StepType.assert_] = StepType.assert_
    selectors: SelectorBundle | None = None
    assertion: str
    expected: str | None = None
    intent: str


class ScrollStep(BaseModel):
    id: str
    type: Literal[StepType.scroll] = StepType.scroll
    selectors: SelectorBundle | None = None
    delta_x: int = 0
    delta_y: int = 0
    intent: str


class HoverStep(BaseModel):
    id: str
    type: Literal[StepType.hover] = StepType.hover
    selectors: SelectorBundle
    intent: str
    wait: WaitConfig = Field(default_factory=WaitConfig)


class ExtractStep(BaseModel):
    """Extract text content from a highlighted element at replay time."""

    id: str
    type: Literal[StepType.extract] = StepType.extract
    selectors: SelectorBundle
    variable: str | None = None
    recorded_text: str | None = None
    intent: str


# Discriminated union — add new step types here as the schema evolves.
_StepUnion = (
    NavigateStep
    | ClickStep
    | InputStep
    | SelectStep
    | KeyStep
    | WaitStep
    | AssertStep
    | ScrollStep
    | HoverStep
    | ExtractStep
)
Step = Annotated[_StepUnion, Field(discriminator="type")]


# ---------------------------------------------------------------------------
# Top-level Recording
# ---------------------------------------------------------------------------


class Recording(BaseModel):
    """A complete, portable, self-describing workflow."""

    version: str = SCHEMA_VERSION
    name: str
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    start_url: str
    viewport: Viewport = Field(default_factory=Viewport)
    variables: list[Variable] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def variable_names(self) -> set[str]:
        return {v.name for v in self.variables}

    def secret_variable_names(self) -> set[str]:
        return {v.name for v in self.variables if v.secret}
