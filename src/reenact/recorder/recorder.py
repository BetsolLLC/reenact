"""Browser recorder — launches Playwright, injects JS, collects events → Recording."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from playwright.async_api import Frame, Page, async_playwright

from reenact.schema import (
    ClickStep,
    HoverStep,
    InputStep,
    KeyStep,
    NavigateStep,
    Recording,
    ScrollStep,
    SelectStep,
    Step,
    Viewport,
    WaitConfig,
    WaitStrategy,
)

from .selectorgen import build_intent, build_selector_bundle

_INJECTED_JS = (Path(__file__).parent / "injected.js").read_text(encoding="utf-8")

_PASSWORD_TYPES = {"password"}

AutomationFn = Callable[[Page], Awaitable[None]]


_NOISE_TAGS = {"div", "body", "html", "main", "section", "article", "header", "footer", "nav"}


def _is_noise_element(el: dict[str, Any]) -> bool:
    """True for structural containers that have no unique selector info."""
    tag = (el.get("tagName") or "").lower()
    has_targeting = any([
        el.get("id"),
        el.get("dataTestId"),
        el.get("accessibleName"),
        el.get("role"),
        el.get("implicitRole") not in (None, ""),
    ])
    return tag in _NOISE_TAGS and not has_targeting


# ── Event queue (pure; testable without a browser) ───────────────────────────


class EventQueue:
    """Converts raw browser events into typed Step objects."""

    def __init__(self) -> None:
        self._steps: list[Step] = []
        self._counter = 0
        self._last_url: str | None = None

    def _next_id(self) -> str:
        self._counter += 1
        return f"s{self._counter}"

    @property
    def steps(self) -> list[Step]:
        return list(self._steps)

    def handle_navigate(self, url: str) -> None:
        # Skip duplicate consecutive navigates (SPA hash changes produce spurious events).
        if url == self._last_url:
            return
        self._last_url = url
        self._steps.append(
            NavigateStep(
                id=self._next_id(),
                url=url,
                intent=f"Navigate to {url}",
            )
        )

    def process(self, data: dict[str, Any]) -> None:
        event_type: str = str(data.get("type") or "")
        el: dict[str, Any] = dict(data.get("element") or {})

        if event_type == "click":
            selectors = build_selector_bundle(el)
            # Drop noise clicks on structural containers with no targeting info.
            if not selectors.has_any() or _is_noise_element(el):
                return
            self._steps.append(
                ClickStep(
                    id=self._next_id(),
                    selectors=selectors,
                    intent=build_intent("click", el),
                    wait=WaitConfig(strategy=WaitStrategy.actionable),
                )
            )

        elif event_type == "input":
            el_input_type = str(el.get("type") or "").lower()
            value = str(data.get("value") or "")
            if el_input_type in _PASSWORD_TYPES:
                # Never persist password values; use a placeholder.
                field_name = str(el.get("name") or el.get("id") or "password")
                value = f"{{{{{field_name}}}}}"
            selectors = build_selector_bundle(el)
            self._steps.append(
                InputStep(
                    id=self._next_id(),
                    selectors=selectors,
                    value=value,
                    intent=build_intent("input", el),
                    wait=WaitConfig(strategy=WaitStrategy.actionable),
                )
            )

        elif event_type == "select":
            selectors = build_selector_bundle(el)
            self._steps.append(
                SelectStep(
                    id=self._next_id(),
                    selectors=selectors,
                    value=str(data.get("value") or ""),
                    intent=build_intent("select", {**el, "value": data.get("value")}),
                    wait=WaitConfig(strategy=WaitStrategy.actionable),
                )
            )

        elif event_type == "key":
            key = str(data.get("key") or "")
            selectors = build_selector_bundle(el)
            self._steps.append(
                KeyStep(
                    id=self._next_id(),
                    key=key,
                    selectors=selectors,
                    intent=build_intent("key", {**el, "key": key}),
                    wait=WaitConfig(strategy=WaitStrategy.actionable),
                )
            )

        elif event_type == "scroll":
            self._steps.append(
                ScrollStep(
                    id=self._next_id(),
                    delta_x=int(data.get("deltaX") or 0),
                    delta_y=int(data.get("deltaY") or 0),
                    intent="Scroll the page",
                )
            )

        elif event_type == "hover":
            selectors = build_selector_bundle(el)
            self._steps.append(
                HoverStep(
                    id=self._next_id(),
                    selectors=selectors,
                    intent=build_intent("hover", el),
                    wait=WaitConfig(strategy=WaitStrategy.actionable),
                )
            )

    def _post_process(self) -> None:
        """Back-fill wait strategy on clicks that precede a navigate step."""
        for i, step in enumerate(self._steps[:-1]):
            next_step = self._steps[i + 1]
            if isinstance(step, ClickStep) and isinstance(next_step, NavigateStep):
                self._steps[i] = step.model_copy(
                    update={"wait": WaitConfig(strategy=WaitStrategy.navigation, timeout_ms=15000)}
                )


# ── Recorder ─────────────────────────────────────────────────────────────────


class Recorder:
    def __init__(self, name: str) -> None:
        self.name = name
        self._queue = EventQueue()

    async def record(
        self,
        url: str,
        headed: bool = True,
        automation: AutomationFn | None = None,
        record_video_path: Path | None = None,
    ) -> Recording:
        """
        Launch the browser, collect events, and return a Recording.

        When `automation` is provided it is called with the live Page after
        the initial navigation; recording stops when it returns.  This is
        used by tests to drive the browser programmatically.

        When `automation` is None the recorder waits for the user to close
        the browser window (normal interactive usage).

        When `record_video_path` is provided the browser session is recorded
        to that path as a .webm file (Playwright built-in, no extra deps).
        """
        start_url = url
        viewport = Viewport(width=1280, height=800)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not headed)
            if record_video_path is not None:
                record_video_path.parent.mkdir(parents=True, exist_ok=True)
                context = await browser.new_context(
                    viewport={"width": viewport.width, "height": viewport.height},
                    record_video_dir=str(record_video_path.parent),
                    record_video_size={"width": viewport.width, "height": viewport.height},
                )
            else:
                context = await browser.new_context(
                    viewport={"width": viewport.width, "height": viewport.height}
                )
            page = await context.new_page()

            # Binding must be registered before add_init_script / goto.
            await page.expose_binding("__reenact_event", self._on_event)
            await page.add_init_script(_INJECTED_JS)

            # Track main-frame navigations.
            page.on("framenavigated", self._on_frame_navigated)

            await page.goto(url)

            if automation is not None:
                await automation(page)
                video = page.video if record_video_path is not None else None
                # Context must close first to finalize the video before save_as().
                await context.close()
                if video is not None and record_video_path is not None:
                    await video.save_as(record_video_path)
                await browser.close()
            else:
                # On macOS, Cmd+W closes the page (tab) but leaves the Chromium
                # process alive in the dock.  page.on('close') fires reliably on
                # Cmd+W; we then explicitly close the browser to kill the process.
                page_done = asyncio.Event()

                async def _on_page_close(_page: Page) -> None:
                    page_done.set()

                page.on("close", _on_page_close)
                await page_done.wait()
                with contextlib.suppress(Exception):
                    await browser.close()

        self._queue._post_process()
        return Recording(
            name=self.name,
            start_url=start_url,
            viewport=viewport,
            steps=self._queue.steps,
        )

    # ── Playwright callbacks ──────────────────────────────────────────────────

    def _on_frame_navigated(self, frame: Frame) -> None:
        # Only track the main frame; ignore iframes.
        if frame.parent_frame is not None:
            return
        self._queue.handle_navigate(frame.url)

    def _on_event(self, source: Any, data: Any) -> None:
        if isinstance(data, dict):
            self._queue.process(data)
