# Reenact — CLAUDE.md

## What this project is

Browser record/replay tool. Record once → portable JSON workflow → replay deterministically.
**Zero AI/LLM deps in the core.** No tokens, no model calls, no network calls to AI providers.

## Hard constraints

| Constraint | Value |
|---|---|
| Python | 3.12+ |
| Layout | `src/` layout, packaged with **hatchling** |
| Deps managed | **uv** |
| Browser automation | **Playwright** async API only |
| Schema | **Pydantic v2** |
| CLI | **Typer** + **Rich** |
| Lint/format | **ruff** |
| Types | **mypy --strict** — CI gate, must pass clean |
| Tests | **pytest + pytest-asyncio** |
| License | MIT |
| AI/LLM | NEVER a runtime dep in core |
| Sleeps | NEVER `time.sleep` — use Playwright auto-waiting |

## Selector priority (the whole fallback mechanism)

```
testid → role → text → css → xpath
```

First strategy yielding **exactly one visible match** wins.
`selectorgen` must always compute ARIA role + accessible name — never let the bundle degrade to css/xpath only.

## Schema versioning

- Current: `"1.0"` (`schema.py::SCHEMA_VERSION`)
- Migrations go in `migrations.py::MIGRATIONS` dict keyed by `(from_version, to_version)`
- JSON Schema auto-exported to `schema/reenact.schema.json` via `Recording.model_json_schema()`

## Secret handling

- `Variable(secret=True)` values **never write to disk**
- Prompted at runtime via `--var-secret name` or read from env
- Never record password-field values in plaintext — store a placeholder

## Architecture

```
src/reenact/
  schema.py          # Pydantic models + enums — the source of truth
  migrations.py      # schema version migrations
  storage.py         # load/save recordings (JSON files)
  config.py          # Config dataclass, default dirs
  cli.py             # Typer app — thin; asyncio.run() at command boundary
  recorder/
    recorder.py      # Playwright launch + injected.js binding → Recording
    injected.js      # in-page JS event listeners, posts to Python binding
    selectorgen.py   # builds SelectorBundle per element
  replayer/
    engine.py        # async step executor: resolve → act → wait
    resolver.py      # multi-strategy resolution; iframe + shadow-DOM aware
    waits.py         # WaitStrategy implementations
    result.py        # StepResult, ReplayReport
```

## Build phases

- **Phase 0** (done): Scaffold + schema + CI
- **Phase 1**: Recorder — headed browser, injected JS, selector bundles, intents
- **Phase 2**: Deterministic replayer — resolver + engine + waits + ReplayReport
- **Phase 3**: Parameterization + secrets — `{{var}}` interpolation, prompts, env binding
- **Phase 4**: Polish/ship — README, examples, PyPI publish, export --to playwright

## Running checks locally

```bash
uv run ruff check src/reenact tests    # lint
uv run mypy --strict src/reenact       # types
uv run pytest tests/ -v               # tests
```
