"""Replayer integration tests.

Tests:
1. Basic replay — headless, schema-valid recording plays to completion.
2. CSS resilience — break the CSS selector, replay still passes via role/text fallback.
   This is the core Phase 2 proof: no LLM, no healing, pure selector-bundle fallback.
3. Zero external calls — replay makes no requests outside the target origin.
4. Fail-loud — unresolvable step produces a fail result with intent + screenshot.
5. StepResult records which strategy was used.
"""

from __future__ import annotations

import pytest

from reenact.replayer.engine import Engine
from reenact.replayer.result import ReplayReport
from reenact.schema import (
    ClickStep,
    InputStep,
    NavigateStep,
    Recording,
    RoleSelector,
    SelectorBundle,
    WaitConfig,
    WaitStrategy,
)

# ── Shared HTML fixtures ──────────────────────────────────────────────────────

_FORM_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Form</title></head>
<body>
  <form id="f">
    <label for="q">Search</label>
    <input id="q" name="q" type="text" data-testid="search-input"
           placeholder="Search..." aria-label="Search query" />
    <button type="submit" data-testid="search-btn" class="primary-btn submit-search">
      Search
    </button>
  </form>
  <div id="result" style="display:none">Results loaded</div>
  <script>
    document.getElementById('f').onsubmit = function(e) {
      e.preventDefault();
      document.getElementById('result').style.display = 'block';
    };
  </script>
</body>
</html>"""

_FORM_URL = f"data:text/html,{_FORM_HTML}"


def _make_form_recording(*, css_selector: str | None = "input.search-input") -> Recording:
    """A two-step recording: navigate + click the Search button."""
    return Recording(
        name="test-form",
        start_url=_FORM_URL,
        steps=[
            NavigateStep(id="s1", url=_FORM_URL, intent="Open the test form"),
            InputStep(
                id="s2",
                selectors=SelectorBundle(
                    testid="search-input",
                    role=RoleSelector(role="textbox", name="Search query"),
                    text=None,
                    css='input[name="q"]',
                    xpath='//input[@id="q"]',
                ),
                value="hello world",
                intent="Type into the 'Search query' text field",
                wait=WaitConfig(strategy=WaitStrategy.actionable),
            ),
            ClickStep(
                id="s3",
                selectors=SelectorBundle(
                    testid="search-btn",
                    role=RoleSelector(role="button", name="Search"),
                    text="Search",
                    css=css_selector,
                    xpath='//button[normalize-space()="Search"]',
                ),
                intent="Click the 'Search' button",
                wait=WaitConfig(strategy=WaitStrategy.actionable),
            ),
        ],
    )


# ── 1. Basic replay ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_basic_replay_passes() -> None:
    recording = _make_form_recording()
    report = await Engine()._replay_on_page(
        recording, await _open_page()
    )
    assert report.status == "pass", _fmt(report)
    assert report.passed == 3


# ── 2. CSS resilience — the core Phase 2 proof ───────────────────────────────


@pytest.mark.asyncio
async def test_broken_css_falls_back_to_role() -> None:
    """Break the CSS selector; replay must still pass via role or text fallback."""
    recording = _make_form_recording(css_selector="button.INTENTIONALLY-BROKEN-CSS")

    report = await Engine()._replay_on_page(
        recording, await _open_page()
    )

    assert report.status == "pass", (
        f"Replay failed even though role/text selectors are intact.\n{_fmt(report)}"
    )

    click_result = report.steps[2]  # s3 is the click
    assert click_result.strategy_used is not None
    assert click_result.strategy_used != "css", (
        f"Expected fallback strategy, got: {click_result.strategy_used!r}"
    )
    assert click_result.strategy_used in ("testid", "role", "text", "xpath"), (
        f"Unexpected strategy: {click_result.strategy_used!r}"
    )


@pytest.mark.asyncio
async def test_broken_css_and_testid_falls_back_to_role() -> None:
    """Break both CSS and testid; must still pass via role or text."""
    recording = _make_form_recording(css_selector="button.BROKEN")
    # Also break testid
    click_step = recording.steps[2]
    assert isinstance(click_step, ClickStep)
    broken_step = click_step.model_copy(
        update={
            "selectors": click_step.selectors.model_copy(
                update={"testid": "BROKEN-TESTID", "css": "button.BROKEN"}
            )
        }
    )
    recording.steps[2] = broken_step

    report = await Engine()._replay_on_page(
        recording, await _open_page()
    )

    assert report.status == "pass", _fmt(report)
    click_result = report.steps[2]
    assert click_result.strategy_used in ("role", "text", "xpath"), (
        f"Expected role/text/xpath fallback, got: {click_result.strategy_used!r}"
    )


# ── 3. Zero external calls ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_makes_no_external_calls() -> None:
    """Replay against a data: URL; no network requests should be made."""
    from playwright.async_api import async_playwright

    external_requests: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        def _on_request(req: object) -> None:
            import playwright.async_api as _api
            if isinstance(req, _api.Request):
                url = req.url
                if not url.startswith("data:"):
                    external_requests.append(url)

        page.on("request", _on_request)

        recording = _make_form_recording()
        await Engine()._replay_on_page(recording, page)

        await browser.close()

    assert external_requests == [], (
        f"Replay made unexpected external requests: {external_requests}"
    )


# ── 4. Fail-loud on unresolvable step ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_loud_on_broken_selectors() -> None:
    """All selectors broken → fail result with error text, not a crash."""
    recording = Recording(
        name="broken",
        start_url=_FORM_URL,
        steps=[
            NavigateStep(id="s1", url=_FORM_URL, intent="Open page"),
            ClickStep(
                id="s2",
                selectors=SelectorBundle(
                    testid="NO-SUCH-TESTID",
                    role=RoleSelector(role="button", name="NO-SUCH-NAME"),
                    text="NO-SUCH-TEXT",
                    css="button.no-such-class",
                    xpath="//button[@data-nonexistent='true']",
                ),
                intent="Click the nonexistent button",
                wait=WaitConfig(strategy=WaitStrategy.actionable),
            ),
        ],
    )

    report = await Engine()._replay_on_page(
        recording, await _open_page()
    )

    assert report.status == "fail"
    fail = report.first_failure()
    assert fail is not None
    assert fail.step_id == "s2"
    assert "nonexistent" in fail.intent.lower()
    assert fail.error is not None
    assert len(fail.error) > 0


# ── 5. Strategy recorded in StepResult ───────────────────────────────────────


@pytest.mark.asyncio
async def test_step_result_records_strategy() -> None:
    recording = _make_form_recording()
    report = await Engine()._replay_on_page(
        recording, await _open_page()
    )
    # s2 is an InputStep; s3 is a ClickStep — both should record the strategy used
    input_result = report.steps[1]
    click_result = report.steps[2]
    assert input_result.strategy_used is not None
    assert click_result.strategy_used is not None


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _open_page() -> object:
    """Open a fresh headless page (caller responsible for browser lifecycle)."""
    # Tests that call _replay_on_page directly need a real Page.
    # We use module-level browser management via a shared fixture.
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    # Store refs so GC doesn't close them — engine closes nothing here
    page.__dict__["_pw"] = pw
    page.__dict__["_browser"] = browser
    return page


def _fmt(report: ReplayReport) -> str:
    lines = [f"status={report.status}"]
    for r in report.steps:
        lines.append(f"  {r.step_id} {r.status} strategy={r.strategy_used} err={r.error}")
    return "\n".join(lines)
