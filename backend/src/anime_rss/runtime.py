from datetime import timedelta

from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.downloads.api import DownloadService
from anime_rss.modules.feeds.api import FeedNotFoundError, FeedService
from anime_rss.modules.notifications.api import NotificationService
from anime_rss.modules.operations.api import ClaimedJob, JobService
from anime_rss.modules.operations.ports import (
    DependencyStatus,
    FailedWork,
    JobHandler,
    JobResult,
    JobSchedule,
)
from anime_rss.modules.recognition.api import RecognitionService
from anime_rss.modules.releases.api import ReleaseService
from anime_rss.modules.schedule.api import ScheduleService
from anime_rss.modules.selection.api import SelectionService
from anime_rss.modules.system.backup import BackupService


class ApplicationRuntime:
    """Composition-level adapters for durable background work and diagnostics."""

    def __init__(
        self,
        *,
        feeds: FeedService,
        events: EventDispatcher,
        selection: SelectionService,
        downloads: DownloadService,
        recognition: RecognitionService,
        releases: ReleaseService,
        jobs: JobService,
        notifications: NotificationService,
        schedule: ScheduleService,
        backups: BackupService,
        clock: Clock = utc_now,
        event_interval_seconds: int = 5,
        selection_interval_seconds: int = 10,
        download_interval_seconds: int = 30,
        backup_interval_hours: int = 24,
        schedule_interval_minutes: int = 60,
        retention_interval_hours: int = 24,
        feed_failure_retention_days: int = 7,
        unmatched_retention_days: int = 90,
        operational_history_retention_days: int = 90,
    ) -> None:
        self._feeds = feeds
        self._events = events
        self._selection = selection
        self._downloads = downloads
        self._recognition = recognition
        self._releases = releases
        self._jobs = jobs
        self._notifications = notifications
        self._schedule = schedule
        self._backups = backups
        self._clock = clock
        self._event_interval_seconds = event_interval_seconds
        self._selection_interval_seconds = selection_interval_seconds
        self._download_interval_seconds = download_interval_seconds
        self._backup_interval_hours = backup_interval_hours
        self._schedule_interval_minutes = schedule_interval_minutes
        self._retention_interval_hours = retention_interval_hours
        self._feed_failure_retention_days = feed_failure_retention_days
        self._unmatched_retention_days = unmatched_retention_days
        self._operational_history_retention_days = operational_history_retention_days

    @property
    def handlers(self) -> dict[str, JobHandler]:
        return {
            "feed.refresh": self._refresh_feed,
            "events.dispatch": self._dispatch_events,
            "selection.process_due": self._process_selection,
            "downloads.process_cycle": self._process_downloads,
            "notifications.process_deliveries": self._process_notifications,
            "schedule.sync": self._sync_schedule,
            "system.backup": self._create_backup,
            "system.retention": self._run_retention,
        }

    def schedules(self) -> list[JobSchedule]:
        now = self._clock()
        schedules = [
            JobSchedule("events.dispatch", "singleton", now),
            JobSchedule("selection.process_due", "singleton", now),
            JobSchedule("downloads.process_cycle", "singleton", now),
            JobSchedule("notifications.process_deliveries", "singleton", now),
            JobSchedule("schedule.sync", "singleton", now),
            JobSchedule("system.backup", "daily", now),
            JobSchedule("system.retention", "daily", now),
        ]
        schedules.extend(
            JobSchedule(
                "feed.refresh",
                feed.id,
                feed.next_fetch_at or now,
                payload={"feed_id": feed.id},
                authoritative_due_at=True,
            )
            for feed in self._feeds.list_feeds()
        )
        return schedules

    def dependencies(self) -> list[DependencyStatus]:
        feeds = self._feeds.list_feeds()
        feed_failures = [item for item in feeds if item.health in {"failing", "auth_failed"}]
        if feed_failures:
            feed_status = "degraded"
            feed_summary = f"{len(feed_failures)} 个订阅源需要处理"
        elif feeds:
            feed_status = "healthy"
            feed_summary = f"{len(feeds)} 个订阅源已纳入调度"
        else:
            feed_status = "idle"
            feed_summary = "尚未配置订阅源"

        config = self._downloads.get_config()
        if config is None:
            download_status, download_summary, download_observed = (
                "not_configured",
                "尚未配置 qBittorrent",
                None,
            )
        elif config.last_error_code:
            download_status, download_summary, download_observed = (
                "degraded",
                config.last_error_code,
                config.last_tested_at,
            )
        elif config.last_success_at:
            download_status, download_summary, download_observed = (
                "healthy",
                "最近连接成功",
                config.last_success_at,
            )
        else:
            download_status, download_summary, download_observed = (
                "unknown",
                "配置已保存, 尚未连接成功",
                config.last_tested_at,
            )

        scheduler = self._jobs.get_scheduler_state()
        scheduler_status = scheduler.state if scheduler else "starting"
        scheduler_summary = (
            "调度循环正在持久化运行"
            if scheduler and scheduler.last_success_at
            else "等待首次调度周期"
        )
        return [
            DependencyStatus("feeds", "RSS 订阅源", feed_status, feed_summary),
            DependencyStatus(
                "bangumi", "Bangumi", "on_demand", "按需访问; 失败时使用已有本地元数据"
            ),
            DependencyStatus(
                "qbittorrent",
                "qBittorrent",
                download_status,
                download_summary,
                download_observed,
            ),
            DependencyStatus(
                "scheduler",
                "后台调度",
                scheduler_status,
                scheduler_summary,
                scheduler.updated_at if scheduler else None,
            ),
        ]

    def failed_work(self, *, limit: int = 50) -> list[FailedWork]:
        items: list[FailedWork] = []
        for feed in self._feeds.list_feeds():
            if feed.health not in {"failing", "auth_failed"}:
                continue
            items.append(
                FailedWork(
                    key=f"feed:{feed.id}",
                    kind="feed",
                    title=feed.name,
                    detail="订阅源抓取失败",
                    error_code=feed.error_code,
                    occurred_at=feed.last_attempt_at,
                    action_path=f"/feeds/{feed.id}",
                )
            )
        for task in self._downloads.list_tasks(limit=500):
            if task.state not in {"failed", "externally_removed"}:
                continue
            items.append(
                FailedWork(
                    key=f"download:{task.id}",
                    kind="download",
                    title=task.info_hash,
                    detail="下载任务需要重试或确认外部删除",
                    error_code=task.error_code,
                    occurred_at=task.updated_at,
                    action_path="/downloads",
                )
            )
        for release in self._recognition.list_unmatched(limit=500):
            items.append(
                FailedWork(
                    key=f"recognition:{release.id}",
                    kind="recognition",
                    title=release.source_title,
                    detail="标题无法自动识别, 需要人工映射",
                    error_code=release.reason_code,
                    occurred_at=release.parsed_at,
                    action_path="/candidates",
                )
            )
        for job in self._jobs.list_jobs(limit=500):
            if job.last_error_code is None:
                continue
            items.append(
                FailedWork(
                    key=f"job:{job.id}",
                    kind="scheduler",
                    title=f"{job.job_kind} / {job.dedupe_key}",
                    detail="后台作业执行失败, 已按退避策略重试",
                    error_code=job.last_error_code,
                    occurred_at=job.updated_at,
                    action_path="/operations",
                )
            )
        items.sort(key=lambda item: item.occurred_at or self._clock(), reverse=True)
        return items[: min(max(limit, 1), 500)]

    def _refresh_feed(self, job: ClaimedJob) -> JobResult:
        feed_id = job.payload.get("feed_id")
        if not isinstance(feed_id, str):
            raise ValueError("feed_id_missing")
        feed = next((item for item in self._feeds.list_feeds() if item.id == feed_id), None)
        if feed is None:
            return JobResult(None, {"outcome": "feed_deleted"})
        now = self._clock()
        if feed.next_fetch_at is not None and feed.next_fetch_at > now:
            return JobResult(feed.next_fetch_at, {"outcome": "not_due"})
        try:
            result = self._feeds.refresh_feed(feed_id)
        except FeedNotFoundError:
            return JobResult(None, {"outcome": "feed_deleted"})
        dispatched = self._events.dispatch_until_idle()
        updated = next((item for item in self._feeds.list_feeds() if item.id == feed_id), None)
        next_due_at = updated.next_fetch_at if updated else None
        return JobResult(
            next_due_at,
            {
                "outcome": result.status,
                "new_entries": result.new_entry_count,
                "dispatched_events": dispatched,
            },
        )

    def _dispatch_events(self, job: ClaimedJob) -> JobResult:
        dispatched = self._events.dispatch_until_idle()
        return JobResult(
            self._clock() + timedelta(seconds=self._event_interval_seconds),
            {"dispatched_events": dispatched},
        )

    def _process_selection(self, job: ClaimedJob) -> JobResult:
        processed = self._selection.process_due()
        dispatched = self._events.dispatch_until_idle()
        return JobResult(
            self._clock() + timedelta(seconds=self._selection_interval_seconds),
            {"processed": processed, "dispatched_events": dispatched},
        )

    def _process_downloads(self, job: ClaimedJob) -> JobResult:
        result = self._downloads.process_cycle()
        return JobResult(
            self._clock() + timedelta(seconds=self._download_interval_seconds),
            {
                "submissions": result.submissions,
                "cancellations": result.cancellations,
                "reconciled": result.reconciled,
            },
        )

    def _process_notifications(self, job: ClaimedJob) -> JobResult:
        result = self._notifications.process_deliveries()
        return JobResult(
            self._clock() + timedelta(seconds=30),
            {"delivered": result.delivered, "failed": result.failed},
        )

    def _sync_schedule(self, job: ClaimedJob) -> JobResult:
        result = self._schedule.synchronize()
        dispatched = self._events.dispatch_until_idle()
        return JobResult(
            self._clock() + timedelta(minutes=self._schedule_interval_minutes),
            {
                "generated": result.generated,
                "acquired": result.acquired,
                "missing": result.missing,
                "notifications": result.notifications,
                "dispatched_events": dispatched,
            },
        )

    def _create_backup(self, job: ClaimedJob) -> JobResult:
        result = self._backups.create_backup(reason="scheduled")
        return JobResult(
            self._clock() + timedelta(hours=self._backup_interval_hours),
            {"filename": result.filename, "size_bytes": result.size_bytes},
        )

    def _run_retention(self, job: ClaimedJob) -> JobResult:
        now = self._clock()
        unmatched_before = now - timedelta(days=self._unmatched_retention_days)
        history_before = now - timedelta(days=self._operational_history_retention_days)
        failure_before = now - timedelta(days=self._feed_failure_retention_days)
        retained_release_ids = self._selection.retained_release_ids()
        retained_release_ids.update(self._recognition.permanent_release_ids())
        releases = self._releases.prune_unmatched(
            before=unmatched_before,
            retained_release_ids=retained_release_ids,
        )
        feeds = self._feeds.prune_history(
            failure_before=failure_before,
            history_before=unmatched_before,
        )
        return JobResult(
            now + timedelta(hours=self._retention_interval_hours),
            {
                "feed_fetches_removed": feeds.fetches_removed,
                "feed_entries_removed": feeds.entries_removed + releases.feed_entries_removed,
                "releases_removed": releases.releases_removed,
                "events_removed": self._events.prune_delivered(before=history_before),
                "job_runs_removed": self._jobs.prune_run_history(before=history_before),
            },
        )
