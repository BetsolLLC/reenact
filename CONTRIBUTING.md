# Contributing

## Setup

```bash
git clone https://github.com/yourname/reenact
cd reenact
uv sync
uv run playwright install chromium
```

## Running checks

```bash
uv run ruff check src tests      # lint
uv run mypy --strict src         # type check
uv run pytest tests/ -v          # tests
```

All three must pass before opening a PR. CI enforces this.

## Project layout

```
src/reenact/
  schema.py          # Pydantic v2 models — change here first
  interpolation.py   # {{var}} substitution
  storage.py         # JSON load/save
  recorder/          # browser → Recording
  replayer/          # Recording → ReplayReport
  cli.py             # Typer commands
tests/
  test_schema.py
  test_selectorgen.py
  test_recorder.py
  test_replayer.py
  test_interpolation.py
```

## Adding a new step type

1. Add a new `*Step` model in `schema.py` with a `Literal` type discriminator and `intent: str`.
2. Add it to the `_StepUnion` in `schema.py`.
3. Handle it in `engine.py::_dispatch`.
4. Handle it in `recorder.py::EventQueue.process` (if recordable).
5. Write tests.

## Schema versioning

If you change the JSON schema in a breaking way, bump `SCHEMA_VERSION` in `schema.py` and add a migration in `migrations.py`.

## Selector priority rule

**Do not change the fallback order.** It is: `testid → role → text → css → xpath`. This is a hard architectural constraint documented in `CLAUDE.md`.

## No AI deps in core

`src/reenact` must have zero runtime imports from any AI/LLM provider. The JSON `intent` field exists so an optional external agent layer can read workflows — that tooling is out of scope for this package.
