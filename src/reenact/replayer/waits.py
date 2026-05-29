"""Wait strategy implementations."""

from __future__ import annotations

from playwright.async_api import Page

from reenact.schema import WaitConfig, WaitStrategy


async def apply_wait(page: Page, wait: WaitConfig) -> None:
    """Apply the post-action wait strategy."""
    if wait.strategy == WaitStrategy.navigation:
        await page.wait_for_load_state("domcontentloaded", timeout=wait.timeout_ms)
    elif wait.strategy == WaitStrategy.networkidle:
        await page.wait_for_load_state("networkidle", timeout=wait.timeout_ms)
    elif wait.strategy == WaitStrategy.fixed:
        # page.wait_for_timeout is asyncio-based, not a blocking sleep.
        await page.wait_for_timeout(wait.timeout_ms)
    # WaitStrategy.actionable: no-op — Playwright action methods wait for
    # actionability (visible + enabled) automatically before acting.
