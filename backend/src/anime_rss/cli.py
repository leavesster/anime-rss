from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from anime_rss.config import Settings
from anime_rss.infrastructure.migrations import run_migrations

app = typer.Typer(no_args_is_help=True)


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
