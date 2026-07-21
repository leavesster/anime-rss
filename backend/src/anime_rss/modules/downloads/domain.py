from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class DownloadState(StrEnum):
    PLANNED = "planned"
    RETRYING = "retrying"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    EXTERNALLY_REMOVED = "externally_removed"
    CANCELING = "canceling"
    SUPERSEDED = "superseded"


class DownloadOriginKind(StrEnum):
    SELECTION_DECISION = "selection_decision"
    MANUAL_RELEASE = "manual_release"


@dataclass(frozen=True, slots=True)
class DownloaderConnection:
    base_url: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class Submission:
    info_hash: str
    source_kind: str
    content: bytes
    save_path: str | None
    category: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownloaderTask:
    info_hash: str
    state: str
    progress: float
    save_path: str | None
    category: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownloadCycleResult:
    cancellations: int
    submissions: int
    reconciled: int


class DownloaderError(RuntimeError):
    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


class Downloader(Protocol):
    def test(self, connection: DownloaderConnection) -> str: ...

    def lookup(self, connection: DownloaderConnection, info_hash: str) -> DownloaderTask | None: ...

    def submit(self, connection: DownloaderConnection, submission: Submission) -> None: ...

    def cancel_incomplete(
        self, connection: DownloaderConnection, info_hash: str
    ) -> DownloaderTask | None: ...


def normalize_qbittorrent_state(state: str, progress: float) -> DownloadState:
    lowered = state.lower()
    if lowered in {"error", "missingfiles"}:
        return DownloadState.FAILED
    if lowered.startswith("paused") or lowered.startswith("stopped"):
        return DownloadState.PAUSED
    if progress >= 1 or lowered.endswith("up") or lowered in {"uploading", "stalledup"}:
        return DownloadState.COMPLETED
    return DownloadState.DOWNLOADING
