"""Deterministic replay engine.

Executes each step in order: resolve → act → wait.
Fails loud on the first unresolvable step: records the intent, strategies
tried, and a screenshot path in the StepResult.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from playwright.async_api import Page, async_playwright

from reenact.interpolation import interpolate
from reenact.schema import (
    AssertStep,
    ClickStep,
    HoverStep,
    InputStep,
    KeyStep,
    NavigateStep,
    Recording,
    ScrollStep,
    SelectStep,
    Step,
    WaitConfig,
    WaitStep,
)

from .resolver import ResolverError, resolve
from .result import ReplayReport, StepResult
from .waits import apply_wait

_SCREENSHOT_DIR = Path.home() / ".reenact" / "screenshots"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


class Engine:
    """Async replay engine. One instance per replay run."""

    def __init__(self, screenshot_dir: Path = _SCREENSHOT_DIR) -> None:
        self._screenshot_dir = screenshot_dir
        self._variables: dict[str, str] = {}
        self._secret_names: set[str] = set()

    def set_variables(
        self,
        variables: dict[str, str],
        secret_names: set[str] | None = None,
    ) -> None:
        self._variables = variables
        self._secret_names = secret_names or set()

    async def replay(self, recording: Recording, headed: bool = False) -> ReplayReport:
        """Launch browser, replay all steps, return report."""
        t0 = time.monotonic()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not headed)
            context = await browser.new_context(
                viewport={
                    "width": recording.viewport.width,
                    "height": recording.viewport.height,
                }
            )
            page = await context.new_page()
            report = await self._replay_on_page(recording, page)
            await browser.close()

        report.total_ms = _ms(t0)
        return report

    async def _replay_on_page(
        self, recording: Recording, page: Page
    ) -> ReplayReport:
        """Run all steps on an already-open page (injectable for tests)."""
        results: list[StepResult] = []

        for step in recording.steps:
            result = await self._execute(step, page, recording.name)
            results.append(result)
            if result.status == "fail":
                break  # fail loud — don't continue after a broken step

        overall: ReplayReport = ReplayReport(
            recording_name=recording.name,
            status="pass" if all(r.status == "pass" for r in results) else "fail",
            steps=results,
        )
        return overall

    # ── Step dispatch ─────────────────────────────────────────────────────────

    async def _execute(self, step: Step, page: Page, name: str) -> StepResult:
        t0 = time.monotonic()
        result = await self._dispatch(step, page, name, t0)
        result.step_type = step.type.value
        return result

    async def _dispatch(self, step: Step, page: Page, name: str, t0: float) -> StepResult:
        if isinstance(step, NavigateStep):
            return await self._navigate(step, page, t0)

        if isinstance(step, ClickStep):
            return await self._click(step, page, name, t0)

        if isinstance(step, InputStep):
            return await self._input(step, page, name, t0)

        if isinstance(step, SelectStep):
            return await self._select(step, page, name, t0)

        if isinstance(step, KeyStep):
            return await self._key(step, page, name, t0)

        if isinstance(step, WaitStep):
            return await self._wait(step, page, t0)

        if isinstance(step, AssertStep):
            return await self._assert(step, page, name, t0)

        if isinstance(step, ScrollStep):
            return await self._scroll(step, page, name, t0)

        if isinstance(step, HoverStep):
            return await self._hover(step, page, name, t0)

        return StepResult(
            step_id=step.id,
            intent=step.intent,
            status="skip",
            error=f"Unhandled step type: {step.type}",
        )

    # ── Individual step executors ──────────────────────────────────────────────

    async def _navigate(
        self, step: NavigateStep, page: Page, t0: float
    ) -> StepResult:
        try:
            await page.goto(step.url, wait_until="domcontentloaded")
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                duration_ms=_ms(t0),
            )
        except Exception as exc:
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                duration_ms=_ms(t0),
            )

    async def _click(
        self, step: ClickStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            loc, strategy = await resolve(step.selectors, page)
            await loc.click()
            await apply_wait(page, step.wait)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                strategy_used=strategy,
                duration_ms=_ms(t0),
            )
        except ResolverError as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )
        except Exception as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )

    async def _input(
        self, step: InputStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            value = interpolate(step.value, self._variables)
            loc, strategy = await resolve(step.selectors, page)
            if step.clear_first:
                await loc.clear()
            await loc.fill(value)
            await apply_wait(page, step.wait)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                strategy_used=strategy,
                duration_ms=_ms(t0),
            )
        except (ResolverError, Exception) as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )

    async def _select(
        self, step: SelectStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            value = interpolate(step.value, self._variables)
            loc, strategy = await resolve(step.selectors, page)
            await loc.select_option(value)
            await apply_wait(page, step.wait)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                strategy_used=strategy,
                duration_ms=_ms(t0),
            )
        except (ResolverError, Exception) as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )

    async def _key(
        self, step: KeyStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            if step.selectors:
                loc, strategy = await resolve(step.selectors, page)
                await loc.press(step.key)
            else:
                await page.keyboard.press(step.key)
                strategy = "keyboard"
            await apply_wait(page, step.wait)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                strategy_used=strategy,
                duration_ms=_ms(t0),
            )
        except (ResolverError, Exception) as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )

    async def _wait(self, step: WaitStep, page: Page, t0: float) -> StepResult:
        try:
            cfg = WaitConfig(
                strategy=step.strategy,
                timeout_ms=step.duration_ms or 1000,
            )
            await apply_wait(page, cfg)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                duration_ms=_ms(t0),
            )
        except Exception as exc:
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                duration_ms=_ms(t0),
            )

    async def _assert(
        self, step: AssertStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            resolved_loc = None
            strategy = "page"
            if step.selectors:
                resolved_loc, strategy = await resolve(step.selectors, page)

            passed = False
            if step.assertion == "visible" and resolved_loc is not None:
                passed = await resolved_loc.is_visible()
            elif step.assertion == "url":
                passed = (step.expected or "") in page.url
            elif step.assertion == "title":
                passed = (step.expected or "") in await page.title()
            else:
                passed = True  # unknown assertion type — skip

            step_status: Literal["pass", "fail"] = "pass" if passed else "fail"
            err = (
                None
                if passed
                else f"Assertion '{step.assertion}' failed. Expected {step.expected!r}"
            )
            shot = None if passed else await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status=step_status,
                strategy_used=strategy,
                error=err,
                screenshot=shot,
                duration_ms=_ms(t0),
            )
        except (ResolverError, Exception) as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )

    async def _scroll(
        self, step: ScrollStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            if step.selectors:
                loc, strategy = await resolve(step.selectors, page)
                await loc.scroll_into_view_if_needed()
            else:
                await page.mouse.wheel(step.delta_x, step.delta_y)
                strategy = "page"
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                strategy_used=strategy,
                duration_ms=_ms(t0),
            )
        except (ResolverError, Exception) as exc:
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                duration_ms=_ms(t0),
            )

    async def _hover(
        self, step: HoverStep, page: Page, name: str, t0: float
    ) -> StepResult:
        try:
            loc, strategy = await resolve(step.selectors, page)
            await loc.hover()
            await apply_wait(page, step.wait)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="pass",
                strategy_used=strategy,
                duration_ms=_ms(t0),
            )
        except (ResolverError, Exception) as exc:
            shot = await self._screenshot(page, name, step.id)
            return StepResult(
                step_id=step.id,
                intent=step.intent,
                status="fail",
                error=str(exc),
                screenshot=shot,
                duration_ms=_ms(t0),
            )

    # ── Utility ───────────────────────────────────────────────────────────────

    async def _screenshot(
        self, page: Page, recording_name: str, step_id: str
    ) -> Path | None:
        try:
            d = self._screenshot_dir / recording_name
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"{step_id}.png"
            await page.screenshot(path=str(path))
            return path
        except Exception:
            return None
