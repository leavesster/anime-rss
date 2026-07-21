from dataclasses import dataclass

from sqlalchemy import Engine

from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.infrastructure.http import SafeHttpClient
from anime_rss.modules.feeds.api import FeedService
from anime_rss.modules.operations.api import JobService
from anime_rss.modules.recognition.api import RecognitionService
from anime_rss.modules.releases.api import ReleaseService


@dataclass(slots=True)
class ServiceContainer:
    engine: Engine
    feed_http_client: SafeHttpClient
    torrent_http_client: SafeHttpClient
    feeds: FeedService
    releases: ReleaseService
    recognition: RecognitionService
    jobs: JobService
    events: EventDispatcher

    def close(self) -> None:
        self.feed_http_client.close()
        self.torrent_http_client.close()
        self.engine.dispose()
