"""Browser stealth helpers — reduce automation fingerprint for both recorder and replayer."""

from __future__ import annotations

import platform
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, BrowserType, ViewportSize

# Chromium launch args that suppress the most obvious automation markers.
LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
]

# Realistic desktop Chrome UA — matches what a real macOS Chrome sends.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

# Init script applied to every page before any site JS runs.
# Patches the properties most commonly checked by bot-detection scripts.
INIT_SCRIPT = """
(function () {
  // 1. webdriver flag
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // 2. Plugins — headless reports an empty list; mimic a real browser.
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
  });

  // 3. Languages
  Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
  });

  // 4. window.chrome — absent in headless Chromium.
  if (!window.chrome) {
    Object.defineProperty(window, 'chrome', {
      writable: true, enumerable: true, configurable: false,
      value: { runtime: {} },
    });
  }

  // 5. Permissions — headless returns 'denied' for notifications.
  const origQuery = window.navigator.permissions && window.navigator.permissions.query
    ? window.navigator.permissions.query.bind(window.navigator.permissions)
    : null;
  if (origQuery) {
    window.navigator.permissions.query = (params) =>
      params && params.name === 'notifications'
        ? Promise.resolve({ state: 'default', onchange: null })
        : origQuery(params);
  }

  // 6. outerWidth/outerHeight — headless sets both to 0.
  if (window.outerWidth === 0) {
    Object.defineProperty(window, 'outerWidth',  { get: () => window.innerWidth });
    Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 88 });
  }

  // 7. deviceMemory — headless omits this; real Chrome reports ≥4.
  if (!('deviceMemory' in navigator)) {
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  }

  // 8. hardwareConcurrency — default 2 in headless; real machines have more.
  if (navigator.hardwareConcurrency <= 2) {
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  }
})();
""".strip()


def default_chrome_profile_dir() -> Path:
    """Return the default Chrome user data directory for the current OS."""
    system = platform.system()
    if system == "Windows":
        local_app_data = Path(
            __import__("os").environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        return local_app_data / "Google" / "Chrome" / "User Data"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    # Linux
    return Path.home() / ".config" / "google-chrome"


async def launch_stealth_browser(
    browser_type: BrowserType,
    *,
    headless: bool,
    use_system_chrome: bool = False,
) -> Browser:
    kwargs: dict[str, object] = {"headless": headless, "args": LAUNCH_ARGS}
    if use_system_chrome:
        kwargs["channel"] = "chrome"
    return await browser_type.launch(**kwargs)  # type: ignore[arg-type]


async def new_stealth_context(
    browser: Browser,
    *,
    viewport: dict[str, int],
    record_video_dir: Path | None = None,
    record_video_size: dict[str, int] | None = None,
) -> BrowserContext:
    """Create a browser context with stealth UA + init script."""
    vp = ViewportSize(width=viewport["width"], height=viewport["height"])
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }
    if record_video_dir is not None and record_video_size is not None:
        rvs = ViewportSize(
            width=record_video_size["width"], height=record_video_size["height"]
        )
        context = await browser.new_context(
            viewport=vp,
            user_agent=_USER_AGENT,
            extra_http_headers=headers,
            record_video_dir=str(record_video_dir),
            record_video_size=rvs,
        )
    else:
        context = await browser.new_context(
            viewport=vp,
            user_agent=_USER_AGENT,
            extra_http_headers=headers,
        )
    await context.add_init_script(INIT_SCRIPT)
    return context


async def launch_persistent_context(
    browser_type: BrowserType,
    *,
    user_data_dir: Path,
    headless: bool,
    viewport: dict[str, int],
    use_system_chrome: bool = True,
) -> BrowserContext:
    """Launch Chrome with an existing user profile — carries SSO cookies and session state.

    The returned context is ready to use (no separate browser.new_context() needed).
    Note: Chrome must not already have the profile open, or Playwright will fail to lock it.
    """
    vp = ViewportSize(width=viewport["width"], height=viewport["height"])
    kwargs: dict[str, object] = {
        "headless": headless,
        "args": LAUNCH_ARGS,
        "viewport": vp,
    }
    if use_system_chrome:
        kwargs["channel"] = "chrome"
    context: BrowserContext = await browser_type.launch_persistent_context(
        str(user_data_dir),
        **kwargs,  # type: ignore[arg-type]
    )
    await context.add_init_script(INIT_SCRIPT)
    return context
