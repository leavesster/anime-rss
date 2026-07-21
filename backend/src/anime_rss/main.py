from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request
from sqlalchemy import text

from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.infrastructure.events import EventDispatcher, RegisteredHandler
from anime_rss.infrastructure.http import SafeHttpClient
from anime_rss.infrastructure.migrations import run_migrations
from anime_rss.infrastructure.web import SpaStaticFiles
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.feeds.adapters import FeedDocumentParser
from anime_rss.modules.feeds.api import FeedEntryQueries, FeedService, Jitter
from anime_rss.modules.feeds.http import router as feeds_router
from anime_rss.modules.operations.api import JobService
from anime_rss.modules.releases.api import ReleaseService
from anime_rss.modules.releases.http import router as releases_router
from anime_rss.modules.system.api import FileSecretCipher


def create_app(
    settings: Settings | None = None,
    *,
    feed_transport: httpx.BaseTransport | None = None,
    torrent_transport: httpx.BaseTransport | None = None,
    clock: Clock = utc_now,
    jitter: Jitter | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        runtime_settings.data_dir.mkdir(parents=True, exist_ok=True)
        if runtime_settings.auto_migrate:
            run_migrations(runtime_settings.resolved_database_url)

        cipher = FileSecretCipher.load_or_create(runtime_settings.resolved_master_key_file)
        engine = create_database_engine(runtime_settings.resolved_database_url)
        session_factory = create_session_factory(engine)
        feed_client = SafeHttpClient(
            connect_timeout_seconds=runtime_settings.feed_connect_timeout_seconds,
            read_timeout_seconds=runtime_settings.feed_read_timeout_seconds,
            max_response_bytes=runtime_settings.feed_max_response_bytes,
            transport=feed_transport,
        )
        torrent_client = SafeHttpClient(
            connect_timeout_seconds=runtime_settings.feed_connect_timeout_seconds,
            read_timeout_seconds=runtime_settings.feed_read_timeout_seconds,
            max_response_bytes=2 * 1024 * 1024,
            transport=torrent_transport or feed_transport,
        )
        feed_service_kwargs: dict[str, Any] = {"clock": clock}
        if jitter is not None:
            feed_service_kwargs["jitter"] = jitter
        feeds = FeedService(
            session_factory,
            cipher,
            feed_client,
            FeedDocumentParser(),
            **feed_service_kwargs,
        )
        feed_entries = FeedEntryQueries(session_factory, cipher)
        releases = ReleaseService(
            session_factory, feed_entries, cipher, torrent_client, clock=clock
        )
        events = EventDispatcher(
            session_factory,
            {
                "FeedEntryObserved.v1": [
                    RegisteredHandler(
                        consumer="releases.feed-entry-observer.v1",
                        handler=releases.handle_feed_entry_observed,
                    )
                ]
            },
            clock=clock,
        )
        services = ServiceContainer(
            engine=engine,
            feed_http_client=feed_client,
            torrent_http_client=torrent_client,
            feeds=feeds,
            releases=releases,
            jobs=JobService(session_factory, clock=clock),
            events=events,
        )
        app.state.services = services
        try:
            yield
        finally:
            services.close()

    app = FastAPI(
        title="Anime RSS Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    api = APIRouter(prefix="/api/v1")

    @api.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "alive"}

    @api.get("/health/ready", tags=["health"])
    def readiness(  # pyright: ignore[reportUnusedFunction]
        request: Request,
    ) -> dict[str, str]:
        services: ServiceContainer = request.app.state.services
        with services.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ready"}

    api.include_router(feeds_router)
    api.include_router(releases_router)
    app.include_router(api)

    repository_root = Path(__file__).resolve().parents[3]
    web_dist_dir = runtime_settings.web_dist_dir or repository_root / "web" / "dist"
    if (web_dist_dir / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=web_dist_dir, html=True), name="web")
    return app


app = create_app()
