"""Schema round-trip and validation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reenact.schema import (
    ClickStep,
    InputStep,
    NavigateStep,
    Recording,
    RoleSelector,
    SelectorBundle,
    StepType,
    Variable,
    Viewport,
    WaitConfig,
    WaitStrategy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_recording() -> Recording:
    return Recording(
        name="login_and_search",
        description="Log in and run a search",
        created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=UTC),
        start_url="https://example.com/login",
        viewport=Viewport(width=1280, height=800),
        variables=[
            Variable(name="username", default=None, secret=False),
            Variable(name="password", default=None, secret=True),
        ],
        steps=[
            NavigateStep(
                id="s1",
                type=StepType.navigate,
                url="https://example.com/login",
                intent="Open the login page",
            ),
            InputStep(
                id="s2",
                type=StepType.input,
                selectors=SelectorBundle(
                    testid="login-username",
                    role=RoleSelector(role="textbox", name="Username"),
                    css="#username",
                    xpath="//input[@id='username']",
                    text=None,
                ),
                value="{{username}}",
                intent="Type the username into the username field",
                wait=WaitConfig(strategy=WaitStrategy.actionable, timeout_ms=5000),
            ),
            ClickStep(
                id="s3",
                type=StepType.click,
                selectors=SelectorBundle(
                    testid=None,
                    role=RoleSelector(role="button", name="Sign in"),
                    css="button.primary[type=submit]",
                    xpath="//button[normalize-space()='Sign in']",
                    text="Sign in",
                ),
                intent="Submit the login form",
                wait=WaitConfig(strategy=WaitStrategy.navigation, timeout_ms=10000),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_model_dump_json_and_validate(self, sample_recording: Recording) -> None:
        raw_json = sample_recording.model_dump_json()
        restored = Recording.model_validate_json(raw_json)
        assert restored.name == sample_recording.name
        assert len(restored.steps) == len(sample_recording.steps)

    def test_step_types_preserved(self, sample_recording: Recording) -> None:
        raw = json.loads(sample_recording.model_dump_json())
        restored = Recording.model_validate(raw)
        assert restored.steps[0].type == StepType.navigate
        assert restored.steps[1].type == StepType.input
        assert restored.steps[2].type == StepType.click

    def test_dict_round_trip(self, sample_recording: Recording) -> None:
        data = sample_recording.model_dump()
        restored = Recording.model_validate(data)
        assert restored.version == "1.0"
        assert restored.viewport.width == 1280

    def test_intent_preserved(self, sample_recording: Recording) -> None:
        data = json.loads(sample_recording.model_dump_json())
        restored = Recording.model_validate(data)
        intents = [s.intent for s in restored.steps]
        assert "Open the login page" in intents
        assert "Submit the login form" in intents


# ---------------------------------------------------------------------------
# Schema fields
# ---------------------------------------------------------------------------


class TestSchemaFields:
    def test_secret_variable(self, sample_recording: Recording) -> None:
        assert "password" in sample_recording.secret_variable_names()
        assert "username" not in sample_recording.secret_variable_names()

    def test_variable_names(self, sample_recording: Recording) -> None:
        assert sample_recording.variable_names() == {"username", "password"}

    def test_selector_bundle_has_any(self) -> None:
        full = SelectorBundle(testid="foo")
        empty = SelectorBundle()
        assert full.has_any() is True
        assert empty.has_any() is False

    def test_default_viewport(self) -> None:
        r = Recording(name="x", start_url="https://example.com")
        assert r.viewport.width == 1280
        assert r.viewport.height == 800

    def test_version_default(self) -> None:
        r = Recording(name="x", start_url="https://example.com")
        assert r.version == "1.0"


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------


class TestJsonSchemaExport:
    def test_json_schema_file_exists(self) -> None:
        schema_path = Path(__file__).parent.parent / "schema" / "reenact.schema.json"
        assert schema_path.exists(), "schema/reenact.schema.json must be generated"

    def test_json_schema_is_valid_json(self) -> None:
        schema_path = Path(__file__).parent.parent / "schema" / "reenact.schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert "$defs" in data or "properties" in data

    def test_json_schema_contains_step_types(self) -> None:
        schema_path = Path(__file__).parent.parent / "schema" / "reenact.schema.json"
        raw = schema_path.read_text(encoding="utf-8")
        assert "navigate" in raw
        assert "click" in raw
        assert "intent" in raw


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


class TestMigrations:
    def test_migrate_noop_on_current_version(self) -> None:
        from reenact.migrations import migrate

        data: dict[str, object] = {"version": "1.0", "name": "x"}
        result = migrate(data)
        assert result["version"] == "1.0"
