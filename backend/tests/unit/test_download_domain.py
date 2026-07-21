from anime_rss.modules.downloads.domain import DownloadState, normalize_qbittorrent_state


def test_qbittorrent_states_map_to_product_states() -> None:
    assert normalize_qbittorrent_state("downloading", 0.4) == DownloadState.DOWNLOADING
    assert normalize_qbittorrent_state("pausedDL", 0.4) == DownloadState.PAUSED
    assert normalize_qbittorrent_state("missingFiles", 0.4) == DownloadState.FAILED
    assert normalize_qbittorrent_state("pausedUP", 1.0) == DownloadState.PAUSED
    assert normalize_qbittorrent_state("uploading", 1.0) == DownloadState.COMPLETED
