import asyncio
import hmac
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from sqlalchemy import text

from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.infrastructure.api import (
    ApiErrorResponse,
    HttpIdempotencyStore,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    enrich_openapi_contract,
    error_response,
)
from anime_rss.infrastructure.browser_security import (
    BrowserOriginPolicy,
    BrowserSecurityError,
    RateLimit,
    RequestRateLimiter,
)
from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.infrastructure.events import EventDispatcher, RegisteredHandler
from anime_rss.infrastructure.http import SafeHttpClient
from anime_rss.infrastructure.observability import (
    configure_logging,
    log_event,
    log_exception,
    normalize_correlation_id,
    observation_context,
    shutdown_logging,
)
from anime_rss.infrastructure.web import SpaStaticFiles
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import AuditService
from anime_rss.modules.audit.http import router as audit_router
from anime_rss.modules.catalog.adapters import BangumiClient
from anime_rss.modules.catalog.api import CatalogService
from anime_rss.modules.catalog.http import router as catalog_router
from anime_rss.modules.downloads.adapters import QbittorrentClient
from anime_rss.modules.downloads.api import DownloadService
from anime_rss.modules.downloads.http import router as downloads_router
from anime_rss.modules.feeds.adapters import FeedDocumentParser
from anime_rss.modules.feeds.api import FeedEntryQueries, FeedService, Jitter
from anime_rss.modules.feeds.http import router as feeds_router
from anime_rss.modules.notifications.adapters import WebhookClient
from anime_rss.modules.notifications.api import NotificationService
from anime_rss.modules.notifications.http import router as notifications_router
from anime_rss.modules.operations.api import JobService
from anime_rss.modules.operations.http import router as operations_router
from anime_rss.modules.operations.worker import Scheduler
from anime_rss.modules.recognition.api import RecognitionService
from anime_rss.modules.recognition.http import router as recognition_router
from anime_rss.modules.releases.api import ReleaseService
from anime_rss.modules.releases.http import router as releases_router
from anime_rss.modules.schedule.api import ScheduleService
from anime_rss.modules.schedule.http import router as schedule_router
from anime_rss.modules.selection.api import SelectionService
from anime_rss.modules.selection.http import router as selection_router
from anime_rss.modules.subscriptions.api import SubscriptionService
from anime_rss.modules.subscriptions.http import router as subscriptions_router
from anime_rss.modules.system.api import FileSecretCipher, InstanceSettingsService
from anime_rss.modules.system.auth import AuthService
from anime_rss.modules.system.backup import BackupService
from anime_rss.modules.system.backup_http import router as backup_router
from anime_rss.modules.system.http import (
    CSRF_COOKIE,
    SESSION_COOKIE,
)
from anime_rss.modules.system.http import (
    router as auth_router,
)
from anime_rss.modules.system.settings_http import router as settings_router
from anime_rss.modules.system.startup import StartupService
from anime_rss.runtime import ApplicationRuntime

logger = logging.getLogger(__name__)


async def _run_scheduler(
    scheduler: Scheduler, stop: asyncio.Event, interval_seconds: float
) -> None:
    while not stop.is_set():
        with suppress(Exception):
            await asyncio.to_thread(scheduler.run_once, next_wake_seconds=interval_seconds)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def create_app(
    settings: Settings | None = None,
    *,
    feed_transport: httpx.BaseTransport | None = None,
    torrent_transport: httpx.BaseTransport | None = None,
    bangumi_transport: httpx.BaseTransport | None = None,
    qbittorrent_transport: httpx.BaseTransport | None = None,
    webhook_transport: httpx.BaseTransport | None = None,
    clock: Clock = utc_now,
    jitter: Jitter | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        runtime_settings.data_dir.mkdir(parents=True, exist_ok=True)
        backups = BackupService(
            database_url=runtime_settings.resolved_database_url,
            master_key_file=runtime_settings.resolved_master_key_file,
            data_dir=runtime_settings.data_dir,
            retention_count=runtime_settings.backup_retention_count,
            max_restore_bytes=runtime_settings.backup_max_restore_bytes,
            clock=clock,
        )
        StartupService(
            database_url=runtime_settings.resolved_database_url,
            backups=backups,
            lock_timeout_seconds=runtime_settings.migration_lock_timeout_seconds,
        ).prepare(auto_migrate=runtime_settings.auto_migrate)
        configure_logging(
            data_dir=runtime_settings.data_dir,
            level=runtime_settings.log_level,
            retention_days=runtime_settings.log_retention_days,
        )

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
        qbittorrent_client = QbittorrentClient(
            connect_timeout_seconds=runtime_settings.feed_connect_timeout_seconds,
            read_timeout_seconds=runtime_settings.feed_read_timeout_seconds,
            transport=qbittorrent_transport,
        )
        webhook_client = WebhookClient(
            connect_timeout_seconds=runtime_settings.feed_connect_timeout_seconds,
            read_timeout_seconds=runtime_settings.feed_read_timeout_seconds,
            transport=webhook_transport,
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
        catalog = CatalogService(session_factory, bangumi_client, clock=clock)
        recognition = RecognitionService(session_factory, releases, catalog, clock=clock)
        subscriptions = SubscriptionService(session_factory, catalog, clock=clock)
        selection = SelectionService(session_factory, recognition, subscriptions, clock=clock)
        instance_settings = InstanceSettingsService(session_factory, clock=clock)
        schedule = ScheduleService(
            session_factory,
            catalog,
            subscriptions,
            selection,
            instance_settings,
            clock=clock,
        )
        downloads = DownloadService(
            session_factory,
            cipher,
            qbittorrent_client,
            releases,
            subscriptions,
            clock=clock,
        )
        notifications = NotificationService(session_factory, cipher, webhook_client, clock=clock)
        notification_handlers = {
            event_name: [
                RegisteredHandler(
                    consumer="notifications.integration-events.v1",
                    handler=notifications.handle_event,
                )
            ]
            for event_name in {
                "DecisionCommitted.v1",
                "ManualConfirmationRequired.v1",
                "ReleaseMappingRequired.v1",
                "FeedRepeatedFailure.v1",
                "FeedRecovered.v1",
                "DownloadTaskChanged.v1",
                "EpisodeMissing.v1",
            }
        }
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
                "CatalogTitlesChanged.v1": [
                    RegisteredHandler(
                        consumer="recognition.catalog-title-resolver.v1",
                        handler=recognition.handle_catalog_titles_changed,
                    )
                ],
                "CandidateRemapped.v1": [
                    RegisteredHandler(
                        consumer="selection.candidate-remapped.v1",
                        handler=selection.handle_candidate_remapped,
                    )
                ],
                "CandidateSuperseded.v1": [
                    RegisteredHandler(
                        consumer="selection.candidate-superseded.v1",
                        handler=selection.handle_candidate_superseded,
                    )
                ],
                "CandidateEvaluated.v1": [
                    RegisteredHandler(
                        consumer="selection.candidate-evaluator.v1",
                        handler=selection.handle_candidate_evaluated,
                    )
                ],
                "DownloadRequested.v1": [
                    RegisteredHandler(
                        consumer="downloads.request-planner.v1",
                        handler=downloads.handle_download_requested,
                    )
                ],
                "DownloadCancellationRequested.v1": [
                    RegisteredHandler(
                        consumer="downloads.cancellation-planner.v1",
                        handler=downloads.handle_cancellation_requested,
                    )
                ],
                **notification_handlers,
            },
            clock=clock,
        )
        jobs = JobService(session_factory, clock=clock)
        runtime = ApplicationRuntime(
            feeds=feeds,
            events=events,
            selection=selection,
            downloads=downloads,
            recognition=recognition,
            releases=releases,
            jobs=jobs,
            notifications=notifications,
            schedule=schedule,
            backups=backups,
            clock=clock,
            selection_interval_seconds=max(1, int(runtime_settings.selection_poll_seconds)),
            download_interval_seconds=max(1, int(runtime_settings.download_poll_seconds)),
            backup_interval_hours=runtime_settings.backup_interval_hours,
            retention_interval_hours=runtime_settings.retention_interval_hours,
            feed_failure_retention_days=runtime_settings.feed_failure_retention_days,
            unmatched_retention_days=runtime_settings.unmatched_retention_days,
            operational_history_retention_days=(
                runtime_settings.operational_history_retention_days
            ),
        )
        scheduler = Scheduler(
            jobs,
            handlers=runtime.handlers,
            schedule_sources=[runtime.schedules],
            clock=clock,
            lease_seconds=runtime_settings.scheduler_lease_seconds,
        )
        auth = AuthService(
            session_factory,
            clock=clock,
            session_days=runtime_settings.auth_session_days,
        )
        services = ServiceContainer(
            engine=engine,
            feed_http_client=feed_client,
            torrent_http_client=torrent_client,
            bangumi_client=bangumi_client,
            qbittorrent_client=qbittorrent_client,
            webhook_client=webhook_client,
            feeds=feeds,
            releases=releases,
            recognition=recognition,
            catalog=catalog,
            subscriptions=subscriptions,
            selection=selection,
            downloads=downloads,
            jobs=jobs,
            audit=AuditService(session_factory),
            diagnostics=runtime,
            scheduler=scheduler,
            auth=auth,
            notifications=notifications,
            settings=instance_settings,
            schedule=schedule,
            backups=backups,
            events=events,
        )
        app.state.services = services
        recognition.reconcile_catalog_matches()
        events.dispatch_until_idle(
            event_names={
                "ReleaseIdentified.v1",
                "CandidateEvaluated.v1",
                "DownloadRequested.v1",
                "DownloadCancellationRequested.v1",
            }
        )
        selection.process_due()
        downloads.recover_inflight(force=True)
        downloads.process_cycle()
        scheduler.recover()
        scheduler.run_once(next_wake_seconds=runtime_settings.scheduler_poll_seconds)
        scheduler_stop = asyncio.Event()
        scheduler_task = asyncio.create_task(
            _run_scheduler(scheduler, scheduler_stop, runtime_settings.scheduler_poll_seconds)
        )
        try:
            yield
        finally:
            scheduler_stop.set()
            await scheduler_task
            services.close()
            shutdown_logging()

    app = FastAPI(
        title="Anime RSS Service",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            400: {"model": ApiErrorResponse},
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            412: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
            429: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
            503: {"model": ApiErrorResponse},
        },
    )
    app.state.settings = runtime_settings
    browser_origin_policy = BrowserOriginPolicy(
        trusted_hosts=runtime_settings.resolved_browser_trusted_hosts,
        trusted_origins=runtime_settings.resolved_browser_trusted_origins,
    )
    request_rate_limiter = RequestRateLimiter()
    rate_limits = {
        "/api/v1/auth/setup": RateLimit(
            runtime_settings.auth_rate_limit_attempts,
            runtime_settings.auth_rate_limit_window_seconds,
        ),
        "/api/v1/auth/login": RateLimit(
            runtime_settings.auth_rate_limit_attempts,
            runtime_settings.auth_rate_limit_window_seconds,
        ),
        "/api/v1/feeds/test": RateLimit(
            runtime_settings.connection_test_rate_limit_attempts,
            runtime_settings.connection_test_rate_limit_window_seconds,
        ),
        "/api/v1/downloads/config/test": RateLimit(
            runtime_settings.connection_test_rate_limit_attempts,
            runtime_settings.connection_test_rate_limit_window_seconds,
        ),
        "/api/v1/notifications/config/test": RateLimit(
            runtime_settings.connection_test_rate_limit_attempts,
            runtime_settings.connection_test_rate_limit_window_seconds,
        ),
    }

    @app.exception_handler(HTTPException)
    async def http_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, error: HTTPException
    ) -> Response:
        codes = {
            400: "bad_request",
            401: "authentication_required",
            403: "forbidden",
            404: "resource_not_found",
            409: "conflict",
            412: "precondition_failed",
            413: "request_too_large",
            422: "unprocessable_request",
            428: "precondition_required",
            429: "rate_limited",
            502: "upstream_error",
            503: "service_unavailable",
        }
        message = error.detail
        return error_response(
            request,
            status_code=error.status_code,
            code=codes.get(error.status_code, "http_error"),
            message=message,
            headers=dict(error.headers) if error.headers is not None else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, error: RequestValidationError
    ) -> Response:
        return error_response(
            request,
            status_code=422,
            code="request_validation_failed",
            message="request validation failed",
            details=error.errors(),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, error: Exception
    ) -> Response:
        log_exception(logger, "http.unhandled_error", outcome="failed")
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="request could not be completed",
        )

    @app.middleware("http")
    async def idempotency_boundary(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Any
    ) -> Any:
        excluded = {
            "/api/v1/auth/setup",
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/system/backups/restore/stage",
        }
        key = request.headers.get("idempotency-key")
        if (
            key is None
            or request.method in {"GET", "HEAD", "OPTIONS"}
            or request.url.path in excluded
            or not request.url.path.startswith("/api/v1")
        ):
            return await call_next(request)
        body = await request.body()
        store = HttpIdempotencyStore(request.app.state.services.engine)
        request_hash = store.request_hash(request, body)
        try:
            replay = store.claim(key, request_hash)
        except ValueError as error:
            return error_response(
                request,
                status_code=422,
                code="invalid_idempotency_key",
                message=str(error),
            )
        except IdempotencyConflictError as error:
            return error_response(
                request,
                status_code=409,
                code="idempotency_key_conflict",
                message=str(error),
            )
        except IdempotencyInProgressError as error:
            return error_response(
                request,
                status_code=409,
                code="idempotency_request_in_progress",
                message=str(error),
                headers={"Retry-After": "1"},
            )
        if replay is not None:
            response = Response(
                content=replay.body,
                status_code=replay.status_code,
                headers=replay.headers,
            )
            response.headers["idempotency-replayed"] = "true"
            return response
        try:
            response = await call_next(request)
            response_body = b"".join([chunk async for chunk in response.body_iterator])
        except Exception:
            store.abandon(key, request_hash)
            raise
        replay_headers = {
            name: value
            for name in ("content-type", "location", "etag")
            if (value := response.headers.get(name)) is not None
        }
        if 200 <= response.status_code < 400:
            store.complete(
                key,
                request_hash,
                status_code=response.status_code,
                body=response_body,
                headers=replay_headers,
            )
        else:
            store.abandon(key, request_hash)
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            background=response.background,
        )

    @app.middleware("http")
    async def precondition_boundary(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Any
    ) -> Any:
        if (
            request.url.path.startswith("/api/v1")
            and request.method in {"PUT", "PATCH", "DELETE"}
            and request.headers.get("if-match") is None
        ):
            return error_response(
                request,
                status_code=428,
                code="if_match_required",
                message="If-Match header is required",
            )
        return await call_next(request)

    @app.middleware("http")
    async def rate_limit_boundary(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Any
    ) -> Any:
        policy = rate_limits.get(request.url.path) if request.method == "POST" else None
        if policy is not None:
            client_host = request.client.host if request.client is not None else "unknown"
            retry_after = request_rate_limiter.consume(f"{request.url.path}:{client_host}", policy)
            if retry_after is not None:
                return error_response(
                    request,
                    status_code=429,
                    code="rate_limited",
                    message="request rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)

    @app.middleware("http")
    async def authentication_boundary(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Any
    ) -> Any:
        if not runtime_settings.auth_enabled or not request.url.path.startswith("/api/v1"):
            return await call_next(request)
        public_paths = {
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/auth/status",
            "/api/v1/auth/setup",
            "/api/v1/auth/login",
        }
        if request.url.path in public_paths:
            return await call_next(request)
        services: ServiceContainer = request.app.state.services
        state = services.auth.status()
        if state.setup_required:
            return error_response(
                request,
                status_code=428,
                code="administrator_setup_required",
                message="administrator setup required",
            )
        token = request.cookies.get(SESSION_COOKIE)
        authenticated = services.auth.authenticate(token)
        if authenticated is None:
            return error_response(
                request,
                status_code=401,
                code="authentication_required",
                message="authentication required",
            )
        request.state.auth_session = authenticated
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf_cookie = request.cookies.get(CSRF_COOKIE)
            csrf_header = request.headers.get("x-csrf-token")
            if (
                csrf_cookie is None
                or csrf_header is None
                or not hmac.compare_digest(csrf_cookie, csrf_header)
                or not services.auth.validate_csrf(authenticated.id, csrf_header)
            ):
                return error_response(
                    request,
                    status_code=403,
                    code="csrf_validation_failed",
                    message="csrf validation failed",
                )
        return await call_next(request)

    @app.middleware("http")
    async def browser_security_boundary(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Any
    ) -> Any:
        try:
            browser_origin_policy.validate(request)
        except BrowserSecurityError as error:
            return error_response(
                request,
                status_code=error.status_code,
                code=error.code,
                message=error.message,
            )
        return await call_next(request)

    @app.middleware("http")
    async def correlation_boundary(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Any
    ) -> Any:
        correlation_id = normalize_correlation_id(request.headers.get("x-correlation-id"))
        request.state.correlation_id = correlation_id
        started_at = perf_counter()
        with observation_context(
            correlation_id=correlation_id,
            module="http",
            operation=f"{request.method} {request.url.path}",
        ):
            try:
                response = await call_next(request)
            except Exception:
                log_exception(
                    logger,
                    "http.request_failed",
                    method=request.method,
                    path=request.url.path,
                    duration_ms=round((perf_counter() - started_at) * 1000, 2),
                    outcome="failed",
                )
                raise
            response.headers["x-correlation-id"] = correlation_id
            if request.url.path not in {"/api/v1/health/live", "/api/v1/health/ready"}:
                log_event(
                    logger,
                    "http.request_completed",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=round((perf_counter() - started_at) * 1000, 2),
                    outcome="success" if response.status_code < 500 else "failed",
                )
            return response

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
    api.include_router(auth_router)
    api.include_router(releases_router)
    api.include_router(recognition_router)
    api.include_router(catalog_router)
    api.include_router(subscriptions_router)
    api.include_router(selection_router)
    api.include_router(downloads_router)
    api.include_router(schedule_router)
    api.include_router(operations_router)
    api.include_router(notifications_router)
    api.include_router(backup_router)
    api.include_router(settings_router)
    api.include_router(audit_router)
    app.include_router(api)

    generated_openapi = app.openapi

    def openapi_with_http_contract() -> dict[str, Any]:
        schema = generated_openapi()
        enrich_openapi_contract(schema)
        return schema

    app.openapi = openapi_with_http_contract

    web_dist_dir = runtime_settings.resolved_web_dist_dir
    if (web_dist_dir / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=web_dist_dir, html=True), name="web")
    return app


app = create_app()
