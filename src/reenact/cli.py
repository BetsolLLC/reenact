"""Reenact CLI — Phase 0 stub (commands wired in later phases)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reenact.config import DEFAULT_RECORDINGS_DIR, Config
from reenact.storage import list_recordings, load

app = typer.Typer(name="reenact", help="Browser record/replay tool.")
console = Console()

_recordings_dir_option = typer.Option(
    "--recordings-dir",
    help="Override default recordings directory.",
    envvar="REENACT_RECORDINGS_DIR",
)


def _config(recordings_dir: Path | None, headed: bool = False) -> Config:
    return Config(
        recordings_dir=recordings_dir or DEFAULT_RECORDINGS_DIR,
        headed=headed,
    )


@app.command("list")
def list_(
    recordings_dir: Annotated[Path | None, _recordings_dir_option] = None,
) -> None:
    """List saved recordings."""
    from rich.table import Table

    cfg = _config(recordings_dir)
    names = list_recordings(cfg.recordings_dir)
    if not names:
        console.print("[yellow]No recordings found.[/yellow]")
        return
    table = Table(title="Recordings", show_header=True)
    table.add_column("Name", style="cyan")
    for name in names:
        table.add_row(name)
    console.print(table)


@app.command()
def show(
    name: str,
    recordings_dir: Annotated[Path | None, _recordings_dir_option] = None,
) -> None:
    """Pretty-print a recording's steps and intents."""
    from rich.table import Table

    cfg = _config(recordings_dir)
    recording = load(name, cfg.recordings_dir)
    table = Table(title=f"{recording.name}", show_header=True)
    table.add_column("#", style="dim")
    table.add_column("ID")
    table.add_column("Type", style="cyan")
    table.add_column("Intent")
    for i, step in enumerate(recording.steps, 1):
        table.add_row(str(i), step.id, step.type.value, step.intent)
    console.print(table)


@app.command()
def record(
    name: str,
    url: Annotated[str | None, typer.Option("--url")] = None,
    headed: bool = typer.Option(True, "--headed/--headless"),
    use_chrome: bool = typer.Option(
        False, "--use-chrome/--no-use-chrome",
        help="Use system Google Chrome instead of downloading Playwright's Chromium.",
    ),
    chrome_profile: bool = typer.Option(
        False, "--chrome-profile/--no-chrome-profile",
        help="Use existing Chrome profile (carries SSO sessions). Implies --use-chrome.",
    ),
    recordings_dir: Annotated[Path | None, _recordings_dir_option] = None,
) -> None:
    """Record a browser session."""
    import asyncio

    from reenact.recorder.recorder import Recorder
    from reenact.stealth import default_chrome_profile_dir
    from reenact.storage import save

    cfg = _config(recordings_dir, headed=headed)
    start_url = url or typer.prompt("Start URL")

    if chrome_profile:
        profile_dir = default_chrome_profile_dir()
        if not profile_dir.exists():
            console.print(f"[red]Chrome profile not found: {profile_dir}[/red]")
            console.print("[dim]Close Chrome if it's open and try again, or specify a path.[/dim]")
            raise typer.Exit(1)
        console.print(f"[dim]Using Chrome profile: {profile_dir}[/dim]")
        console.print(
            "[yellow]Close Google Chrome before continuing "
            "(profile must not be locked).[/yellow]"
        )

    console.print(f"[green]Recording '[bold]{name}[/bold]'...[/green]")
    console.print("[dim]Interact with the browser, then close it to finish.[/dim]")

    recorder = Recorder(name=name)
    recording = asyncio.run(recorder.record(
        url=start_url,
        headed=cfg.headed,
        use_system_chrome=use_chrome or chrome_profile,
        chrome_profile_dir=default_chrome_profile_dir() if chrome_profile else None,
    ))

    path = save(recording, cfg.recordings_dir)
    console.print(
        f"[green]Saved [bold]{len(recording.steps)}[/bold] steps → {path}[/green]"
    )


@app.command()
def replay(
    name: str,
    headed: bool = typer.Option(False, "--headed/--headless"),
    use_chrome: bool = typer.Option(
        False, "--use-chrome/--no-use-chrome",
        help="Use system Google Chrome instead of Playwright's Chromium.",
    ),
    recordings_dir: Annotated[Path | None, _recordings_dir_option] = None,
) -> None:
    """Replay a recording deterministically. Fails loud on broken steps."""
    import asyncio

    from rich.table import Table

    from reenact.replayer.engine import Engine
    from reenact.storage import load

    cfg = _config(recordings_dir, headed=headed)
    recording = load(name, cfg.recordings_dir)

    console.print(f"Replaying [bold]{name}[/bold] ({len(recording.steps)} steps) ...")

    engine = Engine()
    report = asyncio.run(engine.replay(recording, headed=cfg.headed, use_system_chrome=use_chrome))

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Type", style="cyan", width=9)
    table.add_column("Intent", no_wrap=False, max_width=45)
    table.add_column("Strategy", width=8)
    table.add_column("ms", justify="right", width=6)
    table.add_column("", width=2)

    for r in report.steps:
        status_icon = "✓" if r.status == "pass" else "✗"
        color = "green" if r.status == "pass" else "red"
        table.add_row(
            r.step_id,
            r.step_type,
            r.intent,
            r.strategy_used or "—",
            str(r.duration_ms),
            f"[{color}]{status_icon}[/{color}]",
        )

    console.print(table)
    console.print(
        f"[bold]{report.passed}/{len(report.steps)} passed[/bold]  "
        f"({report.total_ms}ms total)"
    )

    if report.status == "fail":
        fail = report.first_failure()
        if fail:
            console.print(f"\n[red]FAILED[/red] {fail.step_id}: {fail.intent}")
            console.print(f"  {fail.error}")
            if fail.screenshot:
                console.print(f"  Screenshot: {fail.screenshot}")
        raise typer.Exit(1)


@app.command()
def run(
    name: str,
    var: Annotated[list[str] | None, typer.Option("--var", help="key=value")] = None,
    var_secret: Annotated[
        list[str] | None,
        typer.Option("--var-secret", help="Prompt for secret value at runtime"),
    ] = None,
    headed: bool = typer.Option(False, "--headed/--headless"),
    use_chrome: bool = typer.Option(
        False, "--use-chrome/--no-use-chrome",
        help="Use system Google Chrome instead of Playwright's Chromium.",
    ),
    recordings_dir: Annotated[Path | None, _recordings_dir_option] = None,
) -> None:
    """Replay with variable substitution. Secrets are prompted, never stored."""
    import asyncio

    from rich.table import Table

    from reenact.interpolation import collect_env_vars, mask_secrets
    from reenact.replayer.engine import Engine
    from reenact.storage import load

    cfg = _config(recordings_dir, headed=headed)
    recording = load(name, cfg.recordings_dir)

    # Build variable map: env < --var < --var-secret (highest priority)
    variables: dict[str, str] = {}
    secret_names: set[str] = {v.name for v in recording.variables if v.secret}

    # 1. Defaults from recording schema
    for v in recording.variables:
        if v.default is not None:
            variables[v.name] = v.default

    # 2. Environment variables (REENACT_VAR_<name>)
    variables.update(collect_env_vars(recording.variable_names()))

    # 3. --var overrides
    for pair in var or []:
        if "=" not in pair:
            console.print(f"[red]--var must be key=value, got: {pair!r}[/red]")
            raise typer.Exit(1)
        k, v_val = pair.split("=", 1)
        variables[k] = v_val

    # 4. --var-secret: prompt at runtime, never persist
    secret_values: set[str] = set()
    for secret_name in var_secret or []:
        value = typer.prompt(f"Enter secret '{secret_name}'", hide_input=True)
        variables[secret_name] = value
        secret_values.add(value)

    # Warn about any referenced variables still missing
    from reenact.interpolation import has_placeholder, placeholders_in
    from reenact.schema import InputStep, SelectStep

    missing: set[str] = set()
    for step in recording.steps:
        if isinstance(step, (InputStep, SelectStep)) and has_placeholder(step.value):
            for ph in placeholders_in(step.value):
                if ph not in variables:
                    missing.add(ph)
    if missing:
        console.print(
            f"[yellow]Warning: variables not provided: {sorted(missing)}. "
            f"Steps using them will fail.[/yellow]"
        )

    console.print(f"Running [bold]{name}[/bold] ({len(recording.steps)} steps) ...")

    engine = Engine()
    engine.set_variables(variables, secret_names)
    report = asyncio.run(engine.replay(recording, headed=cfg.headed, use_system_chrome=use_chrome))

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Type", style="cyan", width=9)
    table.add_column("Intent", no_wrap=False, max_width=45)
    table.add_column("Strategy", width=8)
    table.add_column("ms", justify="right", width=6)
    table.add_column("", width=2)

    for r in report.steps:
        status_icon = "✓" if r.status == "pass" else "✗"
        color = "green" if r.status == "pass" else "red"
        # Mask any secret values that leaked into intent strings
        safe_intent = mask_secrets(r.intent, secret_values)
        table.add_row(
            r.step_id,
            r.step_type,
            safe_intent,
            r.strategy_used or "—",
            str(r.duration_ms),
            f"[{color}]{status_icon}[/{color}]",
        )

    console.print(table)
    console.print(
        f"[bold]{report.passed}/{len(report.steps)} passed[/bold]  "
        f"({report.total_ms}ms total)"
    )

    if report.status == "fail":
        fail = report.first_failure()
        if fail:
            safe_error = mask_secrets(fail.error or "", secret_values)
            console.print(f"\n[red]FAILED[/red] {fail.step_id}: {fail.intent}")
            console.print(f"  {safe_error}")
            if fail.screenshot:
                console.print(f"  Screenshot: {fail.screenshot}")
        raise typer.Exit(1)


@app.command()
def edit(
    name: str,
    recordings_dir: Annotated[Path | None, _recordings_dir_option] = None,
) -> None:
    """Open a recording in $EDITOR."""
    import os
    import subprocess

    cfg = _config(recordings_dir)
    path = cfg.recordings_dir / f"{name}.json"
    if not path.exists():
        console.print(f"[red]Not found: {path}[/red]")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(path)], check=False)
