from dataclasses import dataclass

from sqlalchemy import Engine

from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.infrastructure.http import SafeHttpClient
from anime_rss.modules.audit.api import AuditService
from anime_rss.modules.catalog.adapters import BangumiClient
from anime_rss.modules.catalog.api import CatalogService
from anime_rss.modules.downloads.adapters import QbittorrentClient
from anime_rss.modules.downloads.api import DownloadService
from anime_rss.modules.feeds.api import FeedService
from anime_rss.modules.notifications.adapters import WebhookClient
from anime_rss.modules.notifications.api import NotificationService
from anime_rss.modules.operations.api import JobService
from anime_rss.modules.operations.ports import DiagnosticsSource
from anime_rss.modules.operations.worker import Scheduler
from anime_rss.modules.recognition.api import RecognitionService
from anime_rss.modules.releases.api import ReleaseService
from anime_rss.modules.selection.api import SelectionService
from anime_rss.modules.subscriptions.api import SubscriptionService
from anime_rss.modules.system.auth import AuthService
from anime_rss.modules.system.backup import BackupService


@dataclass(slots=True)
class ServiceContainer:
    engine: Engine
    feed_http_client: SafeHttpClient
    torrent_http_client: SafeHttpClient
    bangumi_client: BangumiClient
    qbittorrent_client: QbittorrentClient
    webhook_client: WebhookClient
    feeds: FeedService
    releases: ReleaseService
    recognition: RecognitionService
    catalog: CatalogService
    subscriptions: SubscriptionService
    selection: SelectionService
    downloads: DownloadService
    jobs: JobService
    audit: AuditService
    diagnostics: DiagnosticsSource
    scheduler: Scheduler
    auth: AuthService
    notifications: NotificationService
    backups: BackupService
    events: EventDispatcher

    def close(self) -> None:
        self.feed_http_client.close()
        self.torrent_http_client.close()
        self.bangumi_client.close()
        self.qbittorrent_client.close()
        self.webhook_client.close()
        self.engine.dispose()
