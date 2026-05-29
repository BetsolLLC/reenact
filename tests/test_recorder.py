"""Recorder tests — EventQueue unit tests + headless integration test."""

from __future__ import annotations

import pytest
import pytest_asyncio  # noqa: F401  (imported for asyncio_mode=auto)

from reenact.recorder.recorder import EventQueue, Recorder
from reenact.schema import ClickStep, InputStep, NavigateStep, SelectStep, WaitStrategy

# ── EventQueue unit tests (no browser) ───────────────────────────────────────


class TestEventQueue:
    def test_navigate_adds_step(self) -> None:
        q = EventQueue()
        q.handle_navigate("https://example.com")
        assert len(q.steps) == 1
        assert isinstance(q.steps[0], NavigateStep)
        assert q.steps[0].url == "https://example.com"

    def test_navigate_deduplicates_same_url(self) -> None:
        q = EventQueue()
        q.handle_navigate("https://example.com")
        q.handle_navigate("https://example.com")
        assert len(q.steps) == 1

    def test_navigate_different_urls(self) -> None:
        q = EventQueue()
        q.handle_navigate("https://example.com/a")
        q.handle_navigate("https://example.com/b")
        assert len(q.steps) == 2

    def test_click_event(self) -> None:
        q = EventQueue()
        q.process(
            {
                "type": "click",
                "element": {
                    "tagName": "BUTTON",
                    "implicitRole": "button",
                    "accessibleName": "Submit",
                    "id": None,
                    "dataTestId": None,
                },
                "url": "https://example.com",
            }
        )
        assert len(q.steps) == 1
        step = q.steps[0]
        assert isinstance(step, ClickStep)
        assert "Submit" in step.intent

    def test_input_event(self) -> None:
        q = EventQueue()
        q.process(
            {
                "type": "input",
                "element": {
                    "tagName": "INPUT",
                    "type": "text",
                    "implicitRole": "textbox",
                    "accessibleName": "Username",
                    "id": "user",
                    "dataTestId": "login-user",
                },
                "value": "alice",
                "url": "https://example.com",
            }
        )
        assert len(q.steps) == 1
        step = q.steps[0]
        assert isinstance(step, InputStep)
        assert step.value == "alice"
        assert step.selectors.testid == "login-user"

    def test_password_value_never_stored(self) -> None:
        q = EventQueue()
        q.process(
            {
                "type": "input",
                "element": {
                    "tagName": "INPUT",
                    "type": "password",
                    "implicitRole": "textbox",
                    "accessibleName": "Password",
                    "id": "pass",
                    "name": "password",
                    "dataTestId": None,
                },
                "value": "super_secret_123",
                "url": "https://example.com",
            }
        )
        step = q.steps[0]
        assert isinstance(step, InputStep)
        assert "super_secret_123" not in step.value
        assert "{{" in step.value  # placeholder present

    def test_select_event(self) -> None:
        q = EventQueue()
        q.process(
            {
                "type": "select",
                "element": {
                    "tagName": "SELECT",
                    "implicitRole": "combobox",
                    "accessibleName": "Country",
                    "id": "country",
                    "dataTestId": None,
                },
                "value": "Canada",
                "url": "https://example.com",
            }
        )
        assert len(q.steps) == 1
        step = q.steps[0]
        assert isinstance(step, SelectStep)
        assert step.value == "Canada"

    def test_post_process_sets_navigation_wait(self) -> None:
        q = EventQueue()
        q.process(
            {
                "type": "click",
                "element": {
                    "tagName": "BUTTON",
                    "implicitRole": "button",
                    "accessibleName": "Sign in",
                    "id": None,
                    "dataTestId": None,
                },
                "url": "https://example.com",
            }
        )
        q.handle_navigate("https://example.com/dashboard")
        q._post_process()
        click_step = q.steps[0]
        assert isinstance(click_step, ClickStep)
        assert click_step.wait.strategy == WaitStrategy.navigation

    def test_step_ids_are_unique_and_sequential(self) -> None:
        q = EventQueue()
        q.handle_navigate("https://example.com")
        q.process(
            {
                "type": "click",
                "element": {"tagName": "A", "implicitRole": "link", "accessibleName": "Home"},
                "url": "https://example.com",
            }
        )
        ids = [s.id for s in q.steps]
        assert ids == ["s1", "s2"]

    def test_intent_on_every_step(self) -> None:
        q = EventQueue()
        q.handle_navigate("https://example.com")
        q.process(
            {
                "type": "click",
                "element": {
                    "tagName": "BUTTON",
                    "implicitRole": "button",
                    "accessibleName": "Go",
                    "id": None,
                    "dataTestId": None,
                },
                "url": "https://example.com",
            }
        )
        for step in q.steps:
            assert step.intent, f"Step {step.id} has empty intent"

    def test_selector_bundle_has_role_when_no_testid(self) -> None:
        q = EventQueue()
        q.process(
            {
                "type": "click",
                "element": {
                    "tagName": "BUTTON",
                    "implicitRole": "button",
                    "accessibleName": "Delete",
                    "id": None,
                    "dataTestId": None,
                },
                "url": "https://example.com",
            }
        )
        step = q.steps[0]
        assert isinstance(step, ClickStep)
        assert step.selectors.role is not None, "role must be computed even without testid"
        assert step.selectors.role.role == "button"

    def test_unknown_event_type_is_ignored(self) -> None:
        q = EventQueue()
        q.process({"type": "mousemove", "element": {}, "url": "https://example.com"})
        assert len(q.steps) == 0


# ── Integration test — headless Playwright ────────────────────────────────────


LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Login</title></head>
<body>
  <form id="login-form">
    <label for="username">Username</label>
    <input id="username" name="username" type="text" data-testid="login-username"
           placeholder="Enter username" />
    <label for="password">Password</label>
    <input id="password" name="password" type="password" data-testid="login-password"
           placeholder="Enter password" />
    <button type="submit" data-testid="submit-btn">Sign in</button>
  </form>
  <script>
    document.getElementById('login-form').addEventListener('submit', function(e) {
      e.preventDefault();
      window.location.href = '/dashboard';
    });
  </script>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_recorder_headless_integration() -> None:
    """Full recorder run: headless browser, programmatic interaction, schema-valid output."""
    from playwright.async_api import Page

    recorder = Recorder(name="test_login")

    async def drive(page: Page) -> None:
        # Use the page's data: URL directly
        await page.goto(f"data:text/html,{LOGIN_HTML}")
        await page.locator('[data-testid="login-username"]').fill("alice")
        await page.locator('[data-testid="login-username"]').blur()
        await page.locator('[data-testid="submit-btn"]').click()

    recording = await recorder.record(
        url=f"data:text/html,{LOGIN_HTML}",
        headed=False,
        automation=drive,
    )

    # Schema-valid: must round-trip without error
    raw_json = recording.model_dump_json()
    from reenact.schema import Recording

    restored = Recording.model_validate_json(raw_json)
    assert restored.name == "test_login"

    # Must have captured at least an input and a click
    step_types = {s.type.value for s in recording.steps}
    assert "input" in step_types, f"Expected input step, got: {step_types}"
    assert "click" in step_types, f"Expected click step, got: {step_types}"

    # Every step must have a non-empty intent
    for step in recording.steps:
        assert step.intent, f"Empty intent on step {step.id}"

    # Every interactive step must have ≥2 selector strategies
    for step in recording.steps:
        if isinstance(step, (ClickStep, InputStep, SelectStep)):
            sel = step.selectors
            count = sum(
                1 for v in [sel.testid, sel.role, sel.text, sel.css, sel.xpath] if v is not None
            )
            assert count >= 2, (
                f"Step {step.id} only has {count} selector strategy/ies: {sel}"
            )

    # Password fields must never store plaintext values
    for step in recording.steps:
        if isinstance(step, InputStep):
            assert "super_secret" not in step.value
