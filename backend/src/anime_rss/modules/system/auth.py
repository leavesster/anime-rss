import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.system.api import complete_setup_step
from anime_rss.modules.system.persistence import AdminAccountRecord, AdminSessionRecord

_ADMIN_ID = "administrator"
_LEGACY_SCRYPT_PARAMS = (2**14, 8, 1)
_ARGON2_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


class SetupConflictError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthState:
    setup_required: bool
    authenticated: bool
    username: str | None


@dataclass(frozen=True, slots=True)
class CreatedSession:
    token: str
    csrf_token: str
    expires_at: datetime
    username: str


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    id: str
    account_id: str
    username: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    valid: bool
    needs_rehash: bool = False


class AuthService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock = utc_now,
        session_days: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._session_days = session_days

    def status(self, token: str | None = None) -> AuthState:
        with self._session_factory() as session:
            account = session.get(AdminAccountRecord, _ADMIN_ID)
            if account is None:
                return AuthState(setup_required=True, authenticated=False, username=None)
        authenticated = self.authenticate(token) if token else None
        return AuthState(
            setup_required=False,
            authenticated=authenticated is not None,
            username=authenticated.username if authenticated else None,
        )

    def setup(self, *, username: str, password: str) -> CreatedSession:
        clean_username = self._validate_username(username)
        self._validate_password(password)
        now = self._clock()
        with self._session_factory.begin() as session:
            if session.get(AdminAccountRecord, _ADMIN_ID) is not None:
                raise SetupConflictError("administrator already configured")
            session.add(
                AdminAccountRecord(
                    id=_ADMIN_ID,
                    username=clean_username,
                    password_hash=self._hash_password(password),
                    password_changed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            complete_setup_step(session, step="administrator", now=now)
            record_event(
                session,
                event_type="system.admin_configured",
                entity_type="administrator",
                entity_id=_ADMIN_ID,
            )
        return self._create_session(_ADMIN_ID, clean_username)

    def login(self, *, username: str, password: str) -> CreatedSession:
        with self._session_factory.begin() as session:
            account = session.scalar(
                select(AdminAccountRecord).where(AdminAccountRecord.username == username.strip())
            )
            verification = (
                self._verify_password(password, account.password_hash)
                if account is not None
                else PasswordVerification(valid=False)
            )
            if account is None or not verification.valid:
                raise AuthenticationError("invalid credentials")
            if verification.needs_rehash:
                now = self._clock()
                account.password_hash = self._hash_password(password)
                account.updated_at = now
                record_event(
                    session,
                    event_type="system.password_hash_upgraded",
                    entity_type="administrator",
                    entity_id=account.id,
                )
            account_id = account.id
            clean_username = account.username
        return self._create_session(account_id, clean_username)

    def authenticate(self, token: str | None) -> AuthenticatedSession | None:
        if not token:
            return None
        now = self._clock()
        token_hash = self._token_hash(token)
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(AdminSessionRecord).where(AdminSessionRecord.token_hash == token_hash)
            )
            if record is None or record.expires_at <= now:
                if record is not None:
                    session.delete(record)
                return None
            account = session.get(AdminAccountRecord, record.account_id)
            if account is None:
                session.delete(record)
                return None
            if now - record.last_seen_at >= timedelta(minutes=5):
                record.last_seen_at = now
            return AuthenticatedSession(
                id=record.id,
                account_id=record.account_id,
                username=account.username,
                expires_at=record.expires_at,
            )

    def validate_csrf(self, session_id: str, csrf_token: str | None) -> bool:
        if not csrf_token:
            return False
        with self._session_factory() as session:
            record = session.get(AdminSessionRecord, session_id)
            return record is not None and hmac.compare_digest(
                record.csrf_hash, self._token_hash(csrf_token)
            )

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._session_factory.begin() as session:
            session.execute(
                delete(AdminSessionRecord).where(
                    AdminSessionRecord.token_hash == self._token_hash(token)
                )
            )

    def reset_password(self, password: str) -> None:
        self._validate_password(password)
        now = self._clock()
        with self._session_factory.begin() as session:
            account = session.get(AdminAccountRecord, _ADMIN_ID)
            if account is None:
                raise AuthenticationError("administrator is not configured")
            account.password_hash = self._hash_password(password)
            account.password_changed_at = now
            account.updated_at = now
            session.execute(delete(AdminSessionRecord))
            record_event(
                session,
                event_type="system.password_reset",
                entity_type="administrator",
                entity_id=_ADMIN_ID,
            )

    def purge_expired_sessions(self) -> int:
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(AdminSessionRecord).where(AdminSessionRecord.expires_at <= self._clock())
                ),
            )
            return int(result.rowcount or 0)

    def _create_session(self, account_id: str, username: str) -> CreatedSession:
        now = self._clock()
        expires_at = now + timedelta(days=self._session_days)
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        with self._session_factory.begin() as session:
            session.add(
                AdminSessionRecord(
                    id=new_id(),
                    account_id=account_id,
                    token_hash=self._token_hash(token),
                    csrf_hash=self._token_hash(csrf_token),
                    expires_at=expires_at,
                    last_seen_at=now,
                    created_at=now,
                )
            )
        return CreatedSession(token, csrf_token, expires_at, username)

    @staticmethod
    def _hash_password(password: str) -> str:
        return _ARGON2_HASHER.hash(password)

    @staticmethod
    def _verify_password(password: str, stored: str) -> PasswordVerification:
        if stored.startswith("$argon2id$"):
            try:
                valid = _ARGON2_HASHER.verify(stored, password)
            except (InvalidHashError, VerificationError, VerifyMismatchError):
                return PasswordVerification(valid=False)
            return PasswordVerification(
                valid=valid,
                needs_rehash=valid and _ARGON2_HASHER.check_needs_rehash(stored),
            )
        return PasswordVerification(
            valid=AuthService._verify_legacy_scrypt(password, stored),
            needs_rehash=True,
        )

    @staticmethod
    def _verify_legacy_scrypt(password: str, stored: str) -> bool:
        try:
            version, n_text, r_text, p_text, salt_text, expected_text = stored.split("$")
            if version != "scrypt-v1":
                return False
            params = (int(n_text), int(r_text), int(p_text))
            if params != _LEGACY_SCRYPT_PARAMS:
                return False
            salt = base64.urlsafe_b64decode(salt_text)
            expected = base64.urlsafe_b64decode(expected_text)
            if len(salt) != 16 or len(expected) != 32:
                return False
            actual = hashlib.scrypt(
                password.encode(),
                salt=salt,
                n=params[0],
                r=params[1],
                p=params[2],
                dklen=len(expected),
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _token_hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _validate_username(value: str) -> str:
        username = value.strip()
        if not 1 <= len(username) <= 80:
            raise ValueError("username must contain 1 to 80 characters")
        return username

    @staticmethod
    def _validate_password(value: str) -> None:
        if not 12 <= len(value) <= 256:
            raise ValueError("password must contain 12 to 256 characters")
