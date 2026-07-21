import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.system.persistence import InstanceSettingsRecord

_SETTINGS_ID = "default"
_LANGUAGES = {"zh-CN", "en"}
SETUP_STEPS = (
    "administrator",
    "instance_preferences",
    "qbittorrent_connection",
    "download_defaults",
    "feed",
    "global_preferences",
    "subscription",
    "candidate_preview",
)


class SecretCipher(Protocol):
    def encrypt(self, plaintext: bytes, *, purpose: str) -> bytes: ...

    def decrypt(self, envelope: bytes, *, purpose: str) -> bytes: ...

    def blind_index(self, plaintext: bytes, *, purpose: str) -> str: ...


@dataclass(frozen=True, slots=True)
class InstanceSettings:
    timezone: str
    interface_language: str
    missing_episode_grace_hours: int
    setup_completed_steps: list[str]
    setup_completed: bool
    version: int
    updated_at: datetime | None


def complete_setup_step(
    session: Session,
    *,
    step: str,
    now: datetime,
) -> InstanceSettingsRecord:
    if step not in SETUP_STEPS:
        raise ValueError("unknown setup step")
    record = session.get(InstanceSettingsRecord, _SETTINGS_ID)
    if record is None:
        record = InstanceSettingsRecord(
            id=_SETTINGS_ID,
            timezone="Asia/Shanghai",
            interface_language="zh-CN",
            missing_episode_grace_hours=24,
            setup_completed_steps=[step],
            setup_completed=False,
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
    elif step not in record.setup_completed_steps:
        completed = set(record.setup_completed_steps)
        completed.add(step)
        record.setup_completed_steps = [item for item in SETUP_STEPS if item in completed]
        record.version += 1
        record.updated_at = now
    record.setup_completed = all(item in record.setup_completed_steps for item in SETUP_STEPS)
    return record


class InstanceSettingsService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def get(self) -> InstanceSettings:
        with self._session_factory() as session:
            record = session.get(InstanceSettingsRecord, _SETTINGS_ID)
            if record is None:
                return InstanceSettings(
                    timezone="Asia/Shanghai",
                    interface_language="zh-CN",
                    missing_episode_grace_hours=24,
                    setup_completed_steps=[],
                    setup_completed=False,
                    version=0,
                    updated_at=None,
                )
            return self._to_settings(record)

    def update(
        self,
        *,
        timezone: str,
        interface_language: str,
        missing_episode_grace_hours: int,
        expected_version: int,
    ) -> InstanceSettings:
        timezone = timezone.strip()
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("unknown IANA timezone") from error
        if interface_language not in _LANGUAGES:
            raise ValueError("unsupported interface language")
        if not 1 <= missing_episode_grace_hours <= 168:
            raise ValueError("missing episode grace must be between 1 and 168 hours")
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(InstanceSettingsRecord, _SETTINGS_ID)
            if record is None:
                if expected_version != 0:
                    raise ValueError("instance settings version conflict")
                record = InstanceSettingsRecord(
                    id=_SETTINGS_ID,
                    timezone=timezone,
                    interface_language=interface_language,
                    missing_episode_grace_hours=missing_episode_grace_hours,
                    setup_completed_steps=["instance_preferences"],
                    setup_completed=False,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                if record.version != expected_version:
                    raise ValueError("instance settings version conflict")
                steps = list(record.setup_completed_steps)
                if "instance_preferences" not in steps:
                    steps.append("instance_preferences")
                record.timezone = timezone
                record.interface_language = interface_language
                record.missing_episode_grace_hours = missing_episode_grace_hours
                record.setup_completed_steps = steps
                record.setup_completed = all(item in steps for item in SETUP_STEPS)
                record.version += 1
                record.updated_at = now
        return self.get()

    def mark_setup_step_complete(self, step: str) -> InstanceSettings:
        with self._session_factory.begin() as session:
            complete_setup_step(session, step=step, now=self._clock())
        return self.get()

    @staticmethod
    def _to_settings(record: InstanceSettingsRecord) -> InstanceSettings:
        return InstanceSettings(
            timezone=record.timezone,
            interface_language=record.interface_language,
            missing_episode_grace_hours=record.missing_episode_grace_hours,
            setup_completed_steps=list(record.setup_completed_steps),
            setup_completed=record.setup_completed,
            version=record.version,
            updated_at=record.updated_at,
        )


class AesGcmSecretCipher:
    _VERSION = b"ARS1"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("master key must contain exactly 32 bytes")
        self._key = key
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, purpose: str) -> bytes:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, purpose.encode("utf-8"))
        return self._VERSION + base64.urlsafe_b64encode(nonce + ciphertext)

    def decrypt(self, envelope: bytes, *, purpose: str) -> bytes:
        if not envelope.startswith(self._VERSION):
            raise ValueError("unsupported secret envelope version")
        payload = base64.urlsafe_b64decode(envelope[len(self._VERSION) :])
        if len(payload) < 13:
            raise ValueError("invalid secret envelope")
        return self._cipher.decrypt(payload[:12], payload[12:], purpose.encode("utf-8"))

    def blind_index(self, plaintext: bytes, *, purpose: str) -> str:
        message = purpose.encode("utf-8") + b"\x00" + plaintext
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()


class FileSecretCipher(AesGcmSecretCipher):
    @classmethod
    def load_or_create(cls, path: Path) -> "FileSecretCipher":
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_bytes()
        else:
            key = os.urandom(32)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())

        if len(key) != 32:
            raise ValueError(f"master key at {path} must contain exactly 32 bytes")
        return cls(key)
