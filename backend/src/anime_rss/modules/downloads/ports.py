from datetime import datetime
from typing import Protocol

from anime_rss.modules.downloads.domain import DownloaderConnection
from anime_rss.modules.releases.api import ReleaseDownloadSource
from anime_rss.modules.subscriptions.api import Subscription


class ReleaseSources(Protocol):
    def get_download_source(self, release_id: str) -> ReleaseDownloadSource | None: ...


class SubscriptionQueries(Protocol):
    def get_subscription(self, subscription_id: str) -> Subscription: ...


class ConnectionProvider(Protocol):
    def __call__(self) -> DownloaderConnection: ...


class ConfigResultRecorder(Protocol):
    def __call__(
        self,
        *,
        now: datetime,
        error_code: str | None,
        tested: bool = True,
    ) -> None: ...
