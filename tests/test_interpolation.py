"""Tests for variable interpolation and secret masking."""

from __future__ import annotations

import pytest

from reenact.interpolation import (
    InterpolationError,
    collect_env_vars,
    has_placeholder,
    interpolate,
    mask_secrets,
    placeholders_in,
)
from reenact.replayer.engine import Engine
from reenact.schema import (
    InputStep,
    NavigateStep,
    Recording,
    RoleSelector,
    SelectorBundle,
    Variable,
    WaitConfig,
    WaitStrategy,
)

# ── interpolate() ──────────────────────────────────────────────────────────────


class TestInterpolate:
    def test_single_var(self) -> None:
        assert interpolate("hello {{name}}", {"name": "world"}) == "hello world"

    def test_multiple_vars(self) -> None:
        result = interpolate("{{user}}:{{pass}}", {"user": "alice", "pass": "secret"})
        assert result == "alice:secret"

    def test_no_placeholder(self) -> None:
        assert interpolate("plain text", {}) == "plain text"

    def test_missing_var_raises(self) -> None:
        with pytest.raises(InterpolationError, match="username"):
            interpolate("{{username}}", {})

    def test_empty_string(self) -> None:
        assert interpolate("", {}) == ""

    def test_partial_replacement(self) -> None:
        result = interpolate("{{a}} and {{b}}", {"a": "foo", "b": "bar"})
        assert result == "foo and bar"


class TestHasPlaceholder:
    def test_with_placeholder(self) -> None:
        assert has_placeholder("{{username}}") is True

    def test_without_placeholder(self) -> None:
        assert has_placeholder("plain") is False

    def test_partial_braces(self) -> None:
        assert has_placeholder("{username}") is False


class TestPlaceholdersIn:
    def test_single(self) -> None:
        assert placeholders_in("{{foo}}") == ["foo"]

    def test_multiple(self) -> None:
        assert placeholders_in("{{a}} {{b}}") == ["a", "b"]

    def test_none(self) -> None:
        assert placeholders_in("plain") == []


# ── collect_env_vars() ────────────────────────────────────────────────────────


class TestCollectEnvVars:
    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REENACT_VAR_username", "alice")
        result = collect_env_vars({"username"})
        assert result == {"username": "alice"}

    def test_ignores_unrelated_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTHER_VAR", "x")
        result = collect_env_vars({"username"})
        assert "username" not in result

    def test_missing_returns_empty(self) -> None:
        result = collect_env_vars({"nonexistent_var_xyz"})
        assert result == {}


# ── mask_secrets() ────────────────────────────────────────────────────────────


class TestMaskSecrets:
    def test_masks_secret(self) -> None:
        assert mask_secrets("user=alice pass=s3cr3t", {"s3cr3t"}) == "user=alice pass=***"

    def test_no_secrets_unchanged(self) -> None:
        assert mask_secrets("safe text", set()) == "safe text"

    def test_empty_secret_ignored(self) -> None:
        assert mask_secrets("text", {""}) == "text"

    def test_multiple_secrets(self) -> None:
        result = mask_secrets("a b c", {"a", "c"})
        assert "a" not in result
        assert "c" not in result
        assert "***" in result


# ── Engine with variables ─────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html><html><body>
  <label for="u">User</label>
  <input id="u" data-testid="user-input" aria-label="User" type="text" />
  <label for="p">Pass</label>
  <input id="p" data-testid="pass-input" aria-label="Pass" type="password" />
  <button data-testid="go-btn" type="button">Go</button>
  <div id="out"></div>
  <script>
    document.querySelector('[data-testid="go-btn"]').onclick = function() {
      document.getElementById('out').textContent =
        document.getElementById('u').value + ':' +
        document.getElementById('p').value;
    };
  </script>
</body></html>"""

_URL = f"data:text/html,{_HTML}"


def _var_recording() -> Recording:
    return Recording(
        name="parameterized",
        start_url=_URL,
        variables=[
            Variable(name="username", secret=False),
            Variable(name="password", secret=True),
        ],
        steps=[
            NavigateStep(id="s1", url=_URL, intent="Open page"),
            InputStep(
                id="s2",
                selectors=SelectorBundle(
                    testid="user-input",
                    role=RoleSelector(role="textbox", name="User"),
                ),
                value="{{username}}",
                intent="Type the username",
                wait=WaitConfig(strategy=WaitStrategy.actionable),
            ),
            InputStep(
                id="s3",
                selectors=SelectorBundle(
                    testid="pass-input",
                    role=RoleSelector(role="textbox", name="Pass"),
                ),
                value="{{password}}",
                intent="Type the password",
                wait=WaitConfig(strategy=WaitStrategy.actionable),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_variables_interpolated_at_replay() -> None:
    """{{username}} and {{password}} are substituted at replay, not stored."""
    from playwright.async_api import async_playwright

    recording = _var_recording()
    engine = Engine()
    engine.set_variables({"username": "alice", "password": "hunter2"}, {"password"})

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        report = await engine._replay_on_page(recording, page)

        # Verify values were actually typed into the page
        user_val = await page.locator('[data-testid="user-input"]').input_value()
        pass_val = await page.locator('[data-testid="pass-input"]').input_value()
        await browser.close()

    assert report.status == "pass", str(report)
    assert user_val == "alice"
    assert pass_val == "hunter2"


@pytest.mark.asyncio
async def test_different_inputs_same_recording() -> None:
    """Same recording, different variable values → different behaviour."""
    from playwright.async_api import async_playwright

    recording = _var_recording()

    for username in ("alice", "bob", "carol"):
        engine = Engine()
        engine.set_variables({"username": username, "password": "x"}, {"password"})

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await engine._replay_on_page(recording, page)
            typed = await page.locator('[data-testid="user-input"]').input_value()
            await browser.close()

        assert typed == username, f"Expected {username!r}, got {typed!r}"


@pytest.mark.asyncio
async def test_missing_variable_fails_loud() -> None:
    """A placeholder with no value provided → step fails with clear error."""
    from playwright.async_api import async_playwright

    recording = _var_recording()
    engine = Engine()
    engine.set_variables({}, set())  # no variables provided

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        report = await engine._replay_on_page(recording, page)
        await browser.close()

    assert report.status == "fail"
    fail = report.first_failure()
    assert fail is not None
    assert fail.error is not None
    assert "username" in fail.error or "variable" in fail.error.lower()


@pytest.mark.asyncio
async def test_secret_value_not_in_recording_json() -> None:
    """The secret variable's runtime value must never appear in the JSON schema."""
    recording = _var_recording()
    # The recording JSON must only contain the placeholder, not any actual value
    raw = recording.model_dump_json()
    assert "hunter2" not in raw
    assert "{{password}}" in raw
