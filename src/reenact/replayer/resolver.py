"""Multi-strategy element resolver.

Priority: testid → role → text → css → xpath.
First strategy yielding at least one visible match wins; uses the first
visible element when multiple match (warns in the StepResult).

Iframe descent: if bundle.frame_path is non-empty, navigate into each
frame in order before resolving.

Shadow DOM: Playwright's locators pierce shadow DOM by default.
"""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import FrameLocator, Locator, Page

from reenact.schema import SelectorBundle


class ResolverError(Exception):
    def __init__(self, bundle: SelectorBundle, tried: list[str]) -> None:
        self.bundle = bundle
        self.tried = tried
        parts = [
            f"testid={bundle.testid!r}",
            f"role={bundle.role}",
            f"text={bundle.text!r}",
            f"css={bundle.css!r}",
            f"xpath={bundle.xpath!r}",
        ]
        super().__init__(
            f"No selector resolved after trying {tried}. "
            f"Bundle: {', '.join(parts)}"
        )


async def resolve(
    bundle: SelectorBundle, page: Page, *, max_attempts: int = 3, retry_delay_ms: int = 1500
) -> tuple[Locator, str]:
    """Return (locator, strategy_name) or raise ResolverError.

    Retries up to max_attempts times with retry_delay_ms between attempts to
    handle pages that render content dynamically after domcontentloaded.
    """
    for attempt in range(max_attempts):
        result = await _try_resolve(bundle, page)
        if result is not None:
            return result
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay_ms / 1000)

    # Collect tried strategies for the error message.
    tried = _strategy_names(bundle)
    raise ResolverError(bundle, tried)


def _strategy_names(bundle: SelectorBundle) -> list[str]:
    names: list[str] = []
    if bundle.testid:
        names.append("testid")
    if bundle.role:
        names += ["role", "role~", "role~short"]
    if bundle.text:
        names += ["text", "text~", "text~short"]
    if bundle.css:
        names.append("css")
    if bundle.xpath:
        names.append("xpath")
    return names


async def _try_resolve(bundle: SelectorBundle, page: Page) -> tuple[Locator, str] | None:
    """Single attempt across all strategies; returns None if nothing matched."""
    # Descend into iframes first.
    root: Page | FrameLocator = page
    for frame_sel in bundle.frame_path:
        root = root.frame_locator(frame_sel)

    tried: list[str] = []

    # 1. testid
    if bundle.testid:
        tried.append("testid")
        loc = await _first_visible(root.get_by_test_id(bundle.testid))
        if loc is not None:
            return loc, "testid"

    # 2. role + accessible name
    if bundle.role:
        r = bundle.role
        # 2a. exact name
        tried.append("role")
        role_loc = (
            root.get_by_role(r.role, name=r.name, exact=True)  # type: ignore[arg-type]
            if r.name
            else root.get_by_role(r.role)  # type: ignore[arg-type]
        )
        loc = await _first_visible(role_loc)
        if loc is not None:
            return loc, "role"
        if r.name:
            # 2b. partial name (element accessible-name contains recorded name)
            tried.append("role~")
            loc = await _first_visible(
                root.get_by_role(r.role, name=r.name, exact=False)  # type: ignore[arg-type]
            )
            if loc is not None:
                return loc, "role~"
            # 2c. truncated prefix (recorded name is longer than element text)
            short = _short_text(r.name)
            if short != r.name:
                tried.append("role~short")
                loc = await _first_visible(
                    root.get_by_role(r.role, name=short, exact=False)  # type: ignore[arg-type]
                )
                if loc is not None:
                    return loc, "role~short"

    # 3. visible text
    if bundle.text:
        # 3a. exact
        tried.append("text")
        loc = await _first_visible(root.get_by_text(bundle.text, exact=True))
        if loc is not None:
            return loc, "text"
        # 3b. partial (element text contains recorded text)
        tried.append("text~")
        loc = await _first_visible(root.get_by_text(bundle.text, exact=False))
        if loc is not None:
            return loc, "text~"
        # 3c. truncated prefix (recorded text is longer than element text)
        short = _short_text(bundle.text)
        if short != bundle.text:
            tried.append("text~short")
            loc = await _first_visible(root.get_by_text(short, exact=False))
            if loc is not None:
                return loc, "text~short"

    # 4. CSS selector
    if bundle.css:
        tried.append("css")
        loc = await _first_visible(root.locator(bundle.css))
        if loc is not None:
            return loc, "css"

    # 5. XPath
    if bundle.xpath:
        tried.append("xpath")
        loc = await _first_visible(root.locator(f"xpath={bundle.xpath}"))
        if loc is not None:
            return loc, "xpath"

    return None


_URL_RE = re.compile(r"https?://")
_BREADCRUMB = frozenset("›»·")


def _short_text(text: str, max_words: int = 6) -> str:
    """Return a clean prefix: strips URL noise, breadcrumb chars, and caps word count.

    Handles cases like "TitleBrandhttps://example.com › ..." where the URL is
    concatenated directly onto a word with no whitespace.
    """
    words = text.split()
    clean: list[str] = []
    for w in words:
        # Stop at any word that contains or is a URL / breadcrumb separator.
        if _URL_RE.search(w) or any(c in w for c in _BREADCRUMB) or w == "...":
            break
        clean.append(w)
        if len(clean) >= max_words:
            break
    result = " ".join(clean)
    return result if result else text


async def _first_visible(loc: Locator) -> Locator | None:
    """Return the first visible element from a locator, or None."""
    try:
        count = await loc.count()
        if count == 0:
            return None
        for i in range(min(count, 20)):
            candidate = loc.nth(i)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None
    except Exception:
        return None


# ── Shadow DOM helpers ────────────────────────────────────────────────────────
# Playwright pierces shadow DOM for get_by_role / get_by_text / get_by_test_id
# automatically.  For CSS/XPath selectors inside shadow roots, callers should
# prefix the selector with ":host " or use the >> combinator.
# We expose this utility for edge cases.


def shadow_locator(page: Page, host_css: str, inner_css: str) -> Locator:
    """Locate an element inside a shadow root via the >> combinator."""
    return page.locator(f"{host_css} >> {inner_css}")
