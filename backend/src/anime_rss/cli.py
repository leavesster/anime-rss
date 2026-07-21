from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from anime_rss.acceptance import (
    SoakAcceptanceService,
    SoakNotReadyError,
    render_preflight,
    render_status,
)
from anime_rss.config import Settings
from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.infrastructure.migrations import run_migrations
from anime_rss.modules.system.auth import AuthService
from anime_rss.modules.system.backup import BackupService

app = typer.Typer(no_args_is_help=True)
acceptance_app = typer.Typer(no_args_is_help=True)
app.add_typer(acceptance_app, name="acceptance")


@acceptance_app.command("preflight")
def acceptance_preflight(
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
) -> None:
    checks = SoakAcceptanceService(data_dir).preflight()
    typer.echo(render_preflight(checks))
    if not all(check.passed for check in checks):
        raise typer.Exit(1)


@acceptance_app.command("start")
def acceptance_start(
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
) -> None:
    service = SoakAcceptanceService(data_dir)
    try:
        state = service.start()
    except SoakNotReadyError:
        typer.echo(render_preflight(service.preflight()))
        raise typer.Exit(1) from None
    typer.echo(f"Soak started: {state.started_at.isoformat()}")
    typer.echo(f"Earliest completion: {state.earliest_completion_at.isoformat()}")


@acceptance_app.command("status")
def acceptance_status(
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
) -> None:
    typer.echo(render_status(SoakAcceptanceService(data_dir).status()))


@acceptance_app.command("report")
def acceptance_report(
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    report = SoakAcceptanceService(data_dir).render_report()
    if output is None:
        typer.echo(report, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    typer.echo(str(output))


@app.command()
def migrate(data_dir: Annotated[Path, typer.Option()] = Path("data")) -> None:
    settings = Settings(data_dir=data_dir)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8080,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    uvicorn.run("anime_rss.main:app", host=host, port=port, reload=reload, workers=1)


@app.command("reset-password")
def reset_password(
    password: Annotated[
        str,
        typer.Option(prompt=True, hide_input=True, confirmation_prompt=True),
    ],
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
) -> None:
    settings = Settings(data_dir=data_dir)
    run_migrations(settings.resolved_database_url)
    engine = create_database_engine(settings.resolved_database_url)
    try:
        AuthService(create_session_factory(engine)).reset_password(password)
    finally:
        engine.dispose()
    typer.echo("Administrator password reset; existing sessions were revoked.")


@app.command("backup")
def backup(data_dir: Annotated[Path, typer.Option()] = Path("data")) -> None:
    settings = Settings(data_dir=data_dir)
    service = BackupService(
        database_url=settings.resolved_database_url,
        master_key_file=settings.resolved_master_key_file,
        data_dir=settings.data_dir,
        retention_count=settings.backup_retention_count,
        max_restore_bytes=settings.backup_max_restore_bytes,
    )
    result = service.create_backup()
    typer.echo(str(settings.data_dir / "backups" / result.filename))


@app.command("restore")
def restore(
    archive: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
) -> None:
    settings = Settings(data_dir=data_dir)
    service = BackupService(
        database_url=settings.resolved_database_url,
        master_key_file=settings.resolved_master_key_file,
        data_dir=settings.data_dir,
        retention_count=settings.backup_retention_count,
        max_restore_bytes=settings.backup_max_restore_bytes,
    )
    service.stage_restore(archive)
    typer.echo("Restore staged. Restart the service to apply it.")
