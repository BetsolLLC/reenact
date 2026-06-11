# Reenact

Browser record/replay — deterministic, portable, zero AI deps.

Record a web flow once. Store it as a self-describing JSON workflow. Replay it exactly, with no tokens and no model calls. Resilience comes from capturing multiple selector strategies per element at record time and falling back through them at replay.

```
reenact record login --url https://app.example.com/login
reenact replay login
reenact run    login --var username=alice --var-secret password
```

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — fast Python package manager

---

## Install

### From source (recommended for development)

```bash
git clone https://github.com/BetsolLLC/reenact
cd reenact
uv sync
uv run playwright install chromium
```

### From PyPI

```bash
pip install reenact
playwright install chromium
```

After either install, verify:

```bash
uv run reenact --help   # if installed via uv sync
reenact --help           # if installed via pip
```

> All examples below use `uv run reenact`. Drop `uv run` if installed via pip.

---

## Quick start

### 1. Record a flow

```bash
uv run reenact record my-flow --url https://quotes.toscrape.com --headed
```

A Chromium window opens. Interact with the page — click links, fill inputs, submit forms, navigate. Close the window when done.

The recording is saved to `~/.reenact/recordings/my-flow.json`.

**What gets captured:**

| Action | Notes |
|--------|-------|
| Navigate | Every page load / SPA route change |
| Click | Buttons, links, checkboxes |
| Input | Text fields — captured on blur, not per keystroke |
| Select | `<select>` dropdowns — value, label, and index all captured |
| Key press | Keyboard shortcuts (e.g. Enter, Escape, Tab) |
| Scroll | Page and element scroll |
| Hover | Mouse-over on elements |

**Tips:**
- For text inputs: type, then click elsewhere (captured on blur)
- Password fields are **never** recorded — replaced with `{{password}}` placeholder automatically
- Accidental clicks on blank structural elements (div, body, nav) are filtered out

### 2. Replay

```bash
uv run reenact replay my-flow
```

Headless by default. Add `--headed` to watch it run:

```bash
uv run reenact replay my-flow --headed
```

Output:

```
Replaying my-flow (5 steps) ...
┏━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━┓
┃ ID   ┃ Type      ┃ Intent                        ┃ Strategy   ┃   ms ┃    ┃
┡━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━┩
│ s1   │ navigate  │ Navigate to https://...       │ —          │ 1867 │ ✓  │
│ s2   │ click     │ Click the 'inspirational' link │ role       │ 1288 │ ✓  │
│ s3   │ navigate  │ Navigate to https://...       │ —          │  257 │ ✓  │
└──────┴───────────┴───────────────────────────────┴────────────┴──────┴────┘
3/3 passed  (3412ms total)
```

The **Strategy** column shows which selector won: `testid → role → text → css → xpath → direct-nav`. If the CSS selector breaks after a site redesign, replay falls back to `role` or `text` silently — no AI, no healing, just the fallback chain.

### 3. Run with variables

Use `{{variable_name}}` placeholders in input values during recording, then supply them at replay time.

```bash
# Pass plain values on the command line
uv run reenact run login --var username=alice

# Prompt for a secret at runtime (never stored on disk)
uv run reenact run login --var username=alice --var-secret password

# Set via environment variables (REENACT_VAR_<name>)
REENACT_VAR_username=alice REENACT_VAR_password=secret uv run reenact run login
```

Priority order (highest wins): `--var-secret` > `--var` > `REENACT_VAR_*` env vars > recording defaults.

### 4. Inspect and manage recordings

```bash
uv run reenact list                  # table of all saved recordings
uv run reenact show my-flow          # pretty-print steps and intents
uv run reenact edit my-flow          # open recording JSON in $EDITOR
```

---

## CLI reference

```
reenact record  <name> [--url URL] [--headed/--headless]
reenact replay  <name> [--headed/--headless]
reenact run     <name> [--var key=value]... [--var-secret name]...
reenact list
reenact show    <name>
reenact edit    <name>
```

**Global option:** `--recordings-dir PATH` (default: `~/.reenact/recordings`)

**Env var override:** `REENACT_RECORDINGS_DIR=/path/to/dir reenact list`

---

## Selector fallback chain

For every interactive element, Reenact captures up to five selector strategies at record time and tries them in priority order at replay:

| Priority | Strategy | Source |
|----------|----------|--------|
| 1 | `testid` | `data-testid` attribute |
| 2 | `role` | ARIA role + accessible name |
| 3 | `text` | Visible text content (buttons / links) |
| 4 | `css` | `#id` or `[type][name]` attribute selector |
| 5 | `xpath` | `//tag[@id]` or `//tag[normalize-space()="..."]` |
| — | `direct-nav` | For `<a href>` links: navigates directly instead of clicking |

The first strategy yielding exactly one visible match wins. The `Strategy` column in replay output shows which one was used. If a site redesigns and the CSS selector breaks, `role` or `text` silently takes over.

---

## Variables and secrets

Recordings can reference variables with `{{name}}` syntax in input values.

```json
{ "id": "s2", "type": "input", "value": "{{username}}", ... }
```

Declare variables in the recording (auto-detected from placeholders):

```json
"variables": [
  { "name": "username", "default": null, "secret": false },
  { "name": "password", "default": null, "secret": true }
]
```

**Secrets** (`"secret": true`) are:
- Never written to disk
- Masked in all output and error messages
- Prompted at runtime via `--var-secret` or read from `REENACT_VAR_<name>`

---

## Workflow JSON format

Recordings are plain JSON files, readable and editable by humans:

```json
{
  "version": "1.0",
  "name": "login",
  "start_url": "https://app.example.com/login",
  "variables": [
    { "name": "username", "default": null, "secret": false },
    { "name": "password", "default": null, "secret": true }
  ],
  "steps": [
    {
      "id": "s1", "type": "navigate",
      "url": "https://app.example.com/login",
      "intent": "Navigate to the login page"
    },
    {
      "id": "s2", "type": "input",
      "selectors": {
        "testid": "login-username",
        "role": { "role": "textbox", "name": "Username" },
        "css": "#username",
        "xpath": "//input[@id='username']"
      },
      "value": "{{username}}",
      "intent": "Type the username"
    },
    {
      "id": "s3", "type": "click",
      "selectors": {
        "role": { "role": "button", "name": "Sign in" },
        "text": "Sign in",
        "xpath": "//button[normalize-space()='Sign in']"
      },
      "intent": "Submit the login form",
      "wait": { "strategy": "navigation", "timeout_ms": 10000 }
    }
  ]
}
```

The `intent` field on every step is plain English — human-readable and useful for debugging.

### Supported step types

| Type | Description |
|------|-------------|
| `navigate` | Navigate to a URL |
| `click` | Click an element |
| `input` | Fill a text field |
| `select` | Choose a `<select>` option (by value, label, or index) |
| `key` | Press a keyboard key (e.g. `Enter`, `Tab`, `Escape`) |
| `wait` | Explicit wait (actionable, navigation, networkidle, or fixed ms) |
| `assert` | Assert element presence or text content |
| `scroll` | Scroll page or element |
| `hover` | Hover over an element |

---

## Stealth mode

Both recorder and replayer run with a realistic browser fingerprint to avoid bot-detection blocking:

- `navigator.webdriver` flag is patched to `undefined`
- Realistic Chrome user-agent and `sec-ch-ua` headers
- Plugins, languages, `window.chrome`, permissions, `outerWidth/Height`, `deviceMemory`, and `hardwareConcurrency` all match a real desktop Chrome session

This is transparent — no configuration required.

---

## Development

```bash
git clone https://github.com/BetsolLLC/reenact
cd reenact
uv sync                              # install all deps including dev
uv run playwright install chromium   # install browser binaries

uv run ruff check src tests          # lint
uv run mypy --strict src             # type check (CI gate)
uv run pytest tests/ -v              # run tests
```

CI runs lint → typecheck → tests on every push.

---

## Architecture

```
src/reenact/
  schema.py          # Pydantic v2 models — source of truth for all types
  migrations.py      # schema version migrations (from_ver, to_ver) → fn
  storage.py         # load/save recordings as JSON, auto-migrates on load
  config.py          # Config dataclass, default paths
  interpolation.py   # {{variable}} substitution and secret masking
  stealth.py         # browser fingerprint patching (recorder + replayer)
  cli.py             # Typer app — thin wrappers, asyncio.run at boundaries
  recorder/
    recorder.py      # Playwright session + EventQueue → Recording
    injected.js      # in-page JS event listeners, posts events to Python
    selectorgen.py   # builds SelectorBundle + intent strings per element
  replayer/
    engine.py        # async step executor: resolve → act → wait
    resolver.py      # multi-strategy resolution; iframe + shadow DOM aware
    waits.py         # WaitStrategy implementations
    result.py        # StepResult, ReplayReport
```

### Schema versioning

Current version: `"1.0"`. Migrations are keyed by `(from_version, to_version)` in `migrations.py` and run automatically when loading older recordings.

The JSON Schema is exported to `schema/reenact.schema.json` and can be used for editor validation.

---

## Troubleshooting

**Recording captures no steps**
- Make sure you're interacting with the page — clicks and inputs must happen inside the browser window
- Some pages may block Playwright even with stealth mode; try `--headed` to verify the page loads

**Replay fails on a step**
- Run with `--headed` to watch which step fails
- Check the `Strategy` column — if it shows `—`, no selector matched
- Open the recording with `reenact edit <name>` and verify the selectors are correct
- The site may have changed structure; update the `css` or `xpath` selector in the JSON

**`FileNotFoundError: Recording not found`**
- Run `reenact list` to see available recordings
- Check `--recordings-dir` or `REENACT_RECORDINGS_DIR` if using a custom path

**Secret value appears in output**
- Ensure the variable is declared with `"secret": true` in the recording JSON
- Use `--var-secret` instead of `--var` for sensitive values

---

## License

BSD 3-Clause
