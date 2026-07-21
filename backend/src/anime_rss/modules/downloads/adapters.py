import re
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast

import httpx

from anime_rss.modules.downloads.domain import (
    DownloaderCompatibility,
    DownloaderConnection,
    DownloaderError,
    DownloaderTask,
    Submission,
)

_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_MINIMUM_QBITTORRENT_VERSION = (4, 6, 0)
_MAXIMUM_QBITTORRENT_VERSION = (6, 0, 0)


class QbittorrentClient:
    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._transport = transport

    def close(self) -> None:
        return None

    def test(self, connection: DownloaderConnection) -> DownloaderCompatibility:
        with self._session(connection) as client:
            app_response = self._request(client, "GET", "api/v2/app/version")
            if app_response.status_code != 200:
                self._raise_response(app_response)
            web_api_response = self._request(client, "GET", "api/v2/app/webapiVersion")
            if web_api_response.status_code != 200:
                self._raise_response(web_api_response)
            application_version = app_response.text.strip()
            web_api_version = web_api_response.text.strip()
            app_parts = self._parse_version(application_version)
            api_parts = self._parse_version(web_api_version)
            if app_parts is None or api_parts is None:
                raise DownloaderError("invalid_version_response", transient=False)
            if not (
                _MINIMUM_QBITTORRENT_VERSION <= app_parts < _MAXIMUM_QBITTORRENT_VERSION
                and api_parts[0] == 2
            ):
                raise DownloaderError("unsupported_qbittorrent_version", transient=False)
            return DownloaderCompatibility(
                application_version=application_version[:80],
                web_api_version=web_api_version[:80],
            )

    def lookup(self, connection: DownloaderConnection, info_hash: str) -> DownloaderTask | None:
        with self._session(connection) as client:
            return self._lookup(client, info_hash)

    def submit(self, connection: DownloaderConnection, submission: Submission) -> None:
        data: dict[str, str] = {}
        if submission.save_path:
            data["savepath"] = submission.save_path
        if submission.category:
            data["category"] = submission.category
        if submission.tags:
            data["tags"] = ",".join(submission.tags)

        with self._session(connection) as client:
            if submission.source_kind == "magnet":
                data["urls"] = submission.content.decode("utf-8")
                response = self._request(client, "POST", "api/v2/torrents/add", data=data)
            elif submission.source_kind == "torrent":
                response = self._request(
                    client,
                    "POST",
                    "api/v2/torrents/add",
                    data=data,
                    files={
                        "torrents": (
                            f"{submission.info_hash}.torrent",
                            submission.content,
                            "application/x-bittorrent",
                        )
                    },
                )
            else:
                raise DownloaderError("unsupported_release_payload", transient=False)
            if response.status_code != 200 or response.text.strip() != "Ok.":
                self._raise_response(response, fallback="add_rejected")

    def cancel_incomplete(
        self, connection: DownloaderConnection, info_hash: str
    ) -> DownloaderTask | None:
        with self._session(connection) as client:
            task = self._lookup(client, info_hash)
            if task is None or task.progress >= 1:
                return task
            response = self._request(
                client,
                "POST",
                "api/v2/torrents/delete",
                data={"hashes": info_hash, "deleteFiles": "false"},
            )
            if response.status_code != 200:
                self._raise_response(response, fallback="cancel_rejected")
            return None

    @contextmanager
    def _session(self, connection: DownloaderConnection) -> Generator[httpx.Client]:
        with httpx.Client(
            base_url=connection.base_url.rstrip("/") + "/",
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=False,
        ) as client:
            try:
                response = client.post(
                    "api/v2/auth/login",
                    data={"username": connection.username, "password": connection.password},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                raise DownloaderError("connection_failed", transient=True) from error
            if response.status_code != 200 or response.text.strip() != "Ok.":
                raise DownloaderError("authentication_failed", transient=False)
            yield client

    def _lookup(self, client: httpx.Client, info_hash: str) -> DownloaderTask | None:
        response = self._request(
            client,
            "GET",
            "api/v2/torrents/info",
            params={"hashes": info_hash},
        )
        if response.status_code != 200:
            self._raise_response(response, fallback="lookup_failed")
        try:
            payload = cast(object, response.json())
        except ValueError as error:
            raise DownloaderError("invalid_task_response", transient=False) from error
        if not isinstance(payload, list):
            raise DownloaderError("invalid_task_response", transient=False)
        if not payload:
            return None
        raw = cast(list[object], payload)[0]
        if not isinstance(raw, dict):
            raise DownloaderError("invalid_task_response", transient=False)
        item = cast(dict[str, Any], raw)
        state = item.get("state")
        progress = item.get("progress")
        if not isinstance(state, str) or not isinstance(progress, int | float):
            raise DownloaderError("invalid_task_response", transient=False)
        raw_tags = item.get("tags", "")
        tags = (
            tuple(value.strip() for value in raw_tags.split(",") if value.strip())
            if isinstance(raw_tags, str)
            else ()
        )
        return DownloaderTask(
            info_hash=str(item.get("hash") or info_hash).lower(),
            state=state,
            progress=min(max(float(progress), 0.0), 1.0),
            save_path=item.get("save_path") if isinstance(item.get("save_path"), str) else None,
            category=item.get("category") if isinstance(item.get("category"), str) else None,
            tags=tags,
        )

    @staticmethod
    def _parse_version(value: str) -> tuple[int, int, int] | None:
        matched = _VERSION_PATTERN.fullmatch(value)
        if matched is None:
            return None
        major, minor, patch = matched.groups()
        return int(major), int(minor), int(patch)

    @staticmethod
    def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise DownloaderError("connection_failed", transient=True) from error

    @staticmethod
    def _raise_response(response: httpx.Response, *, fallback: str = "request_rejected") -> None:
        if response.status_code in {401, 403}:
            raise DownloaderError("authentication_failed", transient=False)
        if response.status_code == 429 or response.status_code >= 500:
            raise DownloaderError("upstream_unavailable", transient=True)
        raise DownloaderError(fallback, transient=False)
