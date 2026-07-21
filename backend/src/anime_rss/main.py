import asyncio
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
from anime_rss.modules.catalog.adapters import BangumiClient
from anime_rss.modules.catalog.api import CatalogService
from anime_rss.modules.catalog.http import router as catalog_router
from anime_rss.modules.feeds.adapters import FeedDocumentParser
from anime_rss.modules.feeds.api import FeedEntryQueries, FeedService, Jitter
from anime_rss.modules.feeds.http import router as feeds_router
from anime_rss.modules.operations.api import JobService
from anime_rss.modules.recognition.api import RecognitionService
from anime_rss.modules.recognition.http import router as recognition_router
from anime_rss.modules.releases.api import ReleaseService
from anime_rss.modules.releases.http import router as releases_router
from anime_rss.modules.selection.api import SelectionService
from anime_rss.modules.selection.http import router as selection_router
from anime_rss.modules.subscriptions.api import SubscriptionService
from anime_rss.modules.subscriptions.http import router as subscriptions_router
from anime_rss.modules.system.api import FileSecretCipher


async def _run_selection_deadlines(
    selection: SelectionService, stop: asyncio.Event, interval_seconds: float
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            await asyncio.to_thread(selection.process_due)


def create_app(
    settings: Settings | None = None,
    *,
    feed_transport: httpx.BaseTransport | None = None,
    torrent_transport: httpx.BaseTransport | None = None,
    bangumi_transport: httpx.BaseTransport | None = None,
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
        bangumi_client = BangumiClient(transport=bangumi_transport)
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
        recognition = RecognitionService(session_factory, releases, clock=clock)
        catalog = CatalogService(session_factory, bangumi_client, clock=clock)
        subscriptions = SubscriptionService(session_factory, catalog, clock=clock)
        selection = SelectionService(session_factory, recognition, subscriptions, clock=clock)
        events = EventDispatcher(
            session_factory,
            {
                "FeedEntryObserved.v1": [
                    RegisteredHandler(
                        consumer="releases.feed-entry-observer.v1",
                        handler=releases.handle_feed_entry_observed,
                    )
                ],
                "ReleaseIdentified.v1": [
                    RegisteredHandler(
                        consumer="recognition.release-identifier.v1",
                        handler=recognition.handle_release_identified,
                    )
                ],
                "CandidateEvaluated.v1": [
                    RegisteredHandler(
                        consumer="selection.candidate-evaluator.v1",
                        handler=selection.handle_candidate_evaluated,
                    )
                ],
            },
            clock=clock,
        )
        services = ServiceContainer(
            engine=engine,
            feed_http_client=feed_client,
            torrent_http_client=torrent_client,
            bangumi_client=bangumi_client,
            feeds=feeds,
            releases=releases,
            recognition=recognition,
            catalog=catalog,
            subscriptions=subscriptions,
            selection=selection,
            jobs=JobService(session_factory, clock=clock),
            events=events,
        )
        app.state.services = services
        events.dispatch_until_idle(event_names={"ReleaseIdentified.v1", "CandidateEvaluated.v1"})
        selection.process_due()
        deadline_stop = asyncio.Event()
        deadline_task = asyncio.create_task(
            _run_selection_deadlines(
                selection, deadline_stop, runtime_settings.selection_poll_seconds
            )
        )
        try:
            yield
        finally:
            deadline_stop.set()
            await deadline_task
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
    api.include_router(recognition_router)
    api.include_router(catalog_router)
    api.include_router(subscriptions_router)
    api.include_router(selection_router)
    app.include_router(api)

    repository_root = Path(__file__).resolve().parents[3]
    web_dist_dir = runtime_settings.web_dist_dir or repository_root / "web" / "dist"
    if (web_dist_dir / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=web_dist_dir, html=True), name="web")
    return app


app = create_app()
