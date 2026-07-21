import argparse
import json
import time

from anime_rss.modules.downloads.adapters import QbittorrentClient
from anime_rss.modules.downloads.domain import DownloaderConnection, DownloaderError, Submission

_CONTRACT_HASH = "0123456789abcdef0123456789abcdef01234567"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--expect-version", required=True)
    args = parser.parse_args()

    connection = DownloaderConnection(args.url, args.username, args.password)
    client = QbittorrentClient(connect_timeout_seconds=5, read_timeout_seconds=10)
    compatibility = None
    for _ in range(60):
        try:
            compatibility = client.test(connection)
            break
        except DownloaderError as error:
            if error.code not in {"authentication_failed", "connection_failed"}:
                raise
            time.sleep(0.5)
    if compatibility is None:
        raise RuntimeError("qBittorrent Web API did not become ready")
    if compatibility.application_version != args.expect_version:
        raise RuntimeError(
            f"expected {args.expect_version}, got {compatibility.application_version}"
        )

    client.submit(
        connection,
        Submission(
            info_hash=_CONTRACT_HASH,
            source_kind="magnet",
            content=f"magnet:?xt=urn:btih:{_CONTRACT_HASH}&dn=anime-rss-contract".encode(),
            save_path="/downloads",
            category=None,
            tags=("anime-rss-contract",),
        ),
    )
    observed = None
    for _ in range(40):
        observed = client.lookup(connection, _CONTRACT_HASH)
        if observed is not None:
            break
        time.sleep(0.25)
    if observed is None:
        raise RuntimeError("submitted contract torrent was not observable")
    client.cancel_incomplete(connection, _CONTRACT_HASH)

    print(
        json.dumps(
            {
                "application_version": compatibility.application_version,
                "web_api_version": compatibility.web_api_version,
                "add_lookup_delete": "passed",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
