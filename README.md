# Reenact

Browser record/replay — deterministic, portable, zero AI deps.

Record a web flow once. Store it as a self-describing JSON workflow. Replay it exactly, with no tokens and no model calls. Resilience comes from capturing multiple selector strategies per element at record time and falling back through them at replay.

```
reenact record login --url https://app.example.com/login
reenact replay login
reenact run    login --var user=alice --var-secret password
```

---

## Install

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/BetsolLLC/reenact
cd reenact
uv sync
uv run playwright install chromium
```

---

## Quick start

### 1. Record

```bash
uv run reenact record my-flow --url https://quotes.toscrape.com --headed
```

A Chromium window opens. Interact with the page — click links, fill inputs, navigate. Close the window when done. The recording is saved to `~/.reenact/recordings/my-flow.json`.

**Tips:**
- For text inputs: type, then click elsewhere (captured on blur, not keystroke)
- Password fields are never recorded — replaced with `{{password}}` placeholder automatically
- Accidental clicks on blank page areas are filtered out

### 2. Replay

```bash
uv run reenact replay my-flow
```

Headless by default. Add `--headed` to watch:

```bash
uv run reenact replay my-flow --headed
```

Output:

```
Replaying my-flow (5 steps) ...
┏━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┳━━━━┓
┃ ID   ┃ Type      ┃ Intent                        ┃ Strategy ┃   ms ┃    ┃
┡━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━╇━━━━┩
│ s1   │ navigate  │ Navigate to https://...       │ —        │ 1867 │ ✓  │
│ s2   │ click     │ Click the 'inspirational' link │ role    │ 1288 │ ✓  │
│ s3   │ navigate  │ Navigate to https://...       │ —        │  257 │ ✓  │
└──────┴───────────┴───────────────────────────────┴──────────┴──────┴────┘
3/3 passed  (3412ms total)
```

The **Strategy** column shows which selector was used: `testid → role → text → css → xpath`. If a CSS selector breaks after a site redesign, replay still passes via `role` or `text` — no AI, no healing, just the fallback chain.

### 3. Run with variables

```bash
# Pass values on the command line
uv run reenact run login --var username=alice

# Prompt for a secret at runtime (never stored on disk)
uv run reenact run login --var username=alice --var-secret password

# Or set via environment variables
REENACT_VAR_username=alice REENACT_VAR_password=secret uv run reenact run login
```

### 4. Inspect and manage

```bash
reenact list                  # table of all recordings
reenact show my-flow          # pretty-print steps and intents
reenact edit my-flow          # open JSON in $EDITOR
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

Global option: `--recordings-dir PATH` (default: `~/.reenact/recordings`)
Env var override: `REENACT_RECORDINGS_DIR`

---

## How it works

### Recording

A Playwright-controlled browser launches with an injected JavaScript recorder. The recorder captures every click, input, and navigation and sends events back to Python via `page.expose_binding`. For each element, it computes a full **selector bundle** at capture time:

```
testid  → data-testid attribute
role    → ARIA role + accessible name
text    → visible text content (buttons/links)
css     → #id or [type][name] attribute selector
xpath   → //tag[@id] or //tag[normalize-space()="..."]
```

### Replay

The resolver tries each strategy in priority order (`testid → role → text → css → xpath`). The first one yielding a visible element wins. If the site redesigns and the CSS selector breaks, the role or text fallback takes over silently — the `Strategy` column shows which one was used.

### Workflow JSON

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

The `intent` field on every step is plain English — readable by humans and agent-legible for future tooling.

---

## Development

```bash
uv sync                          # install deps
uv run ruff check src tests      # lint
uv run mypy --strict src         # type check
uv run pytest tests/ -v          # tests
uv run playwright install        # install browser binaries
```

CI runs lint → types → tests on every push (`.github/workflows/ci.yml`).

---

## Architecture

```
src/reenact/
  schema.py          # Pydantic v2 models — the source of truth
  migrations.py      # schema version migrations
  storage.py         # load/save recordings as JSON
  config.py          # Config dataclass, default paths
  cli.py             # Typer app — thin wrappers, asyncio.run at boundary
  recorder/
    recorder.py      # Playwright session + EventQueue → Recording
    injected.js      # in-page JS event listeners
    selectorgen.py   # builds SelectorBundle + intent strings per element
  replayer/
    engine.py        # async step executor: resolve → act → wait
    resolver.py      # multi-strategy resolution; iframe + shadow DOM aware
    waits.py         # WaitStrategy implementations
    result.py        # StepResult, ReplayReport
```

---

## License

BSD 3-Clause
