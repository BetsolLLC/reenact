"""Multi-strategy element resolver.

Priority: testid → role → text → css → xpath.
First strategy yielding at least one visible match wins; uses the first
visible element when multiple match (warns in the StepResult).

Iframe descent: if bundle.frame_path is non-empty, navigate into each
frame in order before resolving.

Shadow DOM: Playwright's locators pierce shadow DOM by default.
"""

from __future__ import annotations

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


async def resolve(bundle: SelectorBundle, page: Page) -> tuple[Locator, str]:
    """Return (locator, strategy_name) or raise ResolverError."""
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

    # 2. role + accessible name (exact match, case-insensitive in Playwright)
    if bundle.role:
        tried.append("role")
        r = bundle.role
        role_loc = (
            root.get_by_role(r.role, name=r.name, exact=True)  # type: ignore[arg-type]
            if r.name
            else root.get_by_role(r.role)  # type: ignore[arg-type]
        )
        loc = await _first_visible(role_loc)
        if loc is not None:
            return loc, "role"

    # 3. visible text (exact)
    if bundle.text:
        tried.append("text")
        loc = await _first_visible(root.get_by_text(bundle.text, exact=True))
        if loc is not None:
            return loc, "text"

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

    raise ResolverError(bundle, tried)


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
