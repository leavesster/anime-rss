import base64
import binascii
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit


class TorrentIdentityKind(StrEnum):
    BTIH = "btih"
    BTMH = "btmh"


@dataclass(frozen=True, slots=True)
class TorrentIdentity:
    identity_kind: TorrentIdentityKind
    identity_value: str
    btih: str | None
    btmh: str | None
    automation_eligible: bool
    torrent_name: str | None


class InvalidTorrent(ValueError):
    pass


def parse_magnet_identity(value: str) -> TorrentIdentity:
    parts = urlsplit(value)
    if parts.scheme.lower() != "magnet":
        raise InvalidTorrent("not_a_magnet")
    query = parse_qs(parts.query)
    exact_topics = query.get("xt", [])
    names = query.get("dn", [])
    torrent_name = _normalize_torrent_name(names[0]) if names else None
    btih = None
    btmh = None
    for topic in exact_topics:
        lowered = topic.lower()
        if lowered.startswith("urn:btih:"):
            btih = _normalize_btih(topic[9:])
        elif lowered.startswith("urn:btmh:"):
            btmh = _normalize_btmh(topic[9:])
    if btih is not None:
        return TorrentIdentity(
            identity_kind=TorrentIdentityKind.BTIH,
            identity_value=btih,
            btih=btih,
            btmh=btmh,
            automation_eligible=True,
            torrent_name=torrent_name,
        )
    if btmh is not None:
        return TorrentIdentity(
            identity_kind=TorrentIdentityKind.BTMH,
            identity_value=btmh,
            btih=None,
            btmh=btmh,
            automation_eligible=False,
            torrent_name=torrent_name,
        )
    raise InvalidTorrent("missing_supported_exact_topic")


def _normalize_btih(value: str) -> str:
    if len(value) == 40:
        try:
            bytes.fromhex(value)
        except ValueError as error:
            raise InvalidTorrent("invalid_btih") from error
        return value.lower()
    if len(value) == 32:
        try:
            decoded = base64.b32decode(value.upper(), casefold=True)
        except binascii.Error as error:
            raise InvalidTorrent("invalid_btih") from error
        if len(decoded) != 20:
            raise InvalidTorrent("invalid_btih")
        return decoded.hex()
    raise InvalidTorrent("invalid_btih")


def _normalize_btmh(value: str) -> str:
    lowered = value.lower()
    if len(lowered) != 68 or not lowered.startswith("1220"):
        raise InvalidTorrent("unsupported_btmh")
    try:
        bytes.fromhex(lowered)
    except ValueError as error:
        raise InvalidTorrent("invalid_btmh") from error
    return lowered


def _normalize_torrent_name(value: str) -> str | None:
    without_controls = "".join(
        character if not unicodedata.category(character).startswith("C") else " "
        for character in value
    )
    normalized = re.sub(r"\s+", " ", without_controls).strip()
    return normalized[:4096] or None


def _torrent_name(fields: dict[bytes, tuple[int, int]], scanner: "_BencodeScanner") -> str | None:
    for key in (b"name.utf-8", b"name"):
        bounds = fields.get(key)
        if bounds is None:
            continue
        start, expected_end = bounds
        try:
            actual_end, raw_name = scanner.scan_bytes(start)
        except InvalidTorrent:
            continue
        if actual_end != expected_end:
            continue
        return _normalize_torrent_name(raw_name.decode("utf-8", errors="replace"))
    return None


class _BencodeScanner:
    def __init__(self, data: bytes, *, max_depth: int = 64, max_keys: int = 100_000) -> None:
        self.data = data
        self.max_depth = max_depth
        self.max_keys = max_keys
        self.keys_seen = 0

    def scan(self, position: int = 0, depth: int = 0) -> int:
        if depth > self.max_depth:
            raise InvalidTorrent("bencode_too_deep")
        if position >= len(self.data):
            raise InvalidTorrent("unexpected_end_of_bencode")
        token = self.data[position]
        if 48 <= token <= 57:
            end, _ = self.scan_bytes(position)
            return end
        if token == ord("i"):
            return self._scan_integer(position)
        if token == ord("l"):
            return self._scan_list(position, depth)
        if token == ord("d"):
            return self._scan_dict(position, depth)
        raise InvalidTorrent("invalid_bencode_token")

    def scan_bytes(self, position: int) -> tuple[int, bytes]:
        separator = self.data.find(b":", position)
        if separator == -1:
            raise InvalidTorrent("invalid_bencode_string")
        length_token = self.data[position:separator]
        if not length_token or not length_token.isdigit():
            raise InvalidTorrent("invalid_bencode_string_length")
        if len(length_token) > 1 and length_token.startswith(b"0"):
            raise InvalidTorrent("noncanonical_bencode_string_length")
        length = int(length_token)
        start = separator + 1
        end = start + length
        if end > len(self.data):
            raise InvalidTorrent("truncated_bencode_string")
        return end, self.data[start:end]

    def dict_fields(self, position: int = 0) -> tuple[int, dict[bytes, tuple[int, int]]]:
        if position >= len(self.data) or self.data[position] != ord("d"):
            raise InvalidTorrent("expected_bencode_dictionary")
        fields: dict[bytes, tuple[int, int]] = {}
        cursor = position + 1
        while True:
            if cursor >= len(self.data):
                raise InvalidTorrent("unterminated_bencode_dictionary")
            if self.data[cursor] == ord("e"):
                return cursor + 1, fields
            cursor, key = self.scan_bytes(cursor)
            self.keys_seen += 1
            if self.keys_seen > self.max_keys:
                raise InvalidTorrent("too_many_bencode_keys")
            if key in fields:
                raise InvalidTorrent("duplicate_bencode_key")
            value_start = cursor
            cursor = self.scan(cursor, 1)
            fields[key] = (value_start, cursor)

    def _scan_integer(self, position: int) -> int:
        end = self.data.find(b"e", position + 1)
        if end == -1:
            raise InvalidTorrent("unterminated_bencode_integer")
        token = self.data[position + 1 : end]
        if not token or token in {b"-0", b"-"}:
            raise InvalidTorrent("invalid_bencode_integer")
        digits = token[1:] if token.startswith(b"-") else token
        if not digits.isdigit() or (len(digits) > 1 and digits.startswith(b"0")):
            raise InvalidTorrent("invalid_bencode_integer")
        return end + 1

    def _scan_list(self, position: int, depth: int) -> int:
        cursor = position + 1
        while True:
            if cursor >= len(self.data):
                raise InvalidTorrent("unterminated_bencode_list")
            if self.data[cursor] == ord("e"):
                return cursor + 1
            cursor = self.scan(cursor, depth + 1)

    def _scan_dict(self, position: int, depth: int) -> int:
        cursor = position + 1
        while True:
            if cursor >= len(self.data):
                raise InvalidTorrent("unterminated_bencode_dictionary")
            if self.data[cursor] == ord("e"):
                return cursor + 1
            cursor, _ = self.scan_bytes(cursor)
            self.keys_seen += 1
            if self.keys_seen > self.max_keys:
                raise InvalidTorrent("too_many_bencode_keys")
            cursor = self.scan(cursor, depth + 1)


def parse_torrent_identity(payload: bytes, *, max_bytes: int = 2 * 1024 * 1024) -> TorrentIdentity:
    if not payload or len(payload) > max_bytes:
        raise InvalidTorrent("torrent_payload_size_invalid")
    scanner = _BencodeScanner(payload)
    document_end, top_fields = scanner.dict_fields()
    if document_end != len(payload):
        raise InvalidTorrent("trailing_bencode_data")
    info_bounds = top_fields.get(b"info")
    if info_bounds is None:
        raise InvalidTorrent("missing_info_dictionary")
    info_start, info_end = info_bounds
    raw_info = payload[info_start:info_end]
    if not raw_info.startswith(b"d"):
        raise InvalidTorrent("invalid_info_dictionary")

    info_scanner = _BencodeScanner(raw_info)
    parsed_end, info_fields = info_scanner.dict_fields()
    if parsed_end != len(raw_info):
        raise InvalidTorrent("invalid_info_dictionary")
    if b"name" not in info_fields or b"piece length" not in info_fields:
        raise InvalidTorrent("incomplete_info_dictionary")
    torrent_name = _torrent_name(info_fields, info_scanner)

    meta_version = info_fields.get(b"meta version")
    is_v2 = meta_version is not None and raw_info[meta_version[0] : meta_version[1]] == b"i2e"
    has_v1_pieces = b"pieces" in info_fields
    has_v2_tree = b"file tree" in info_fields

    if is_v2 and not has_v2_tree:
        raise InvalidTorrent("missing_v2_file_tree")
    if not is_v2 and not has_v1_pieces:
        raise InvalidTorrent("missing_v1_pieces")

    btih = hashlib.sha1(raw_info, usedforsecurity=False).hexdigest() if has_v1_pieces else None
    btmh = "1220" + hashlib.sha256(raw_info).hexdigest() if is_v2 else None
    if btih is not None:
        return TorrentIdentity(
            identity_kind=TorrentIdentityKind.BTIH,
            identity_value=btih,
            btih=btih,
            btmh=btmh,
            automation_eligible=True,
            torrent_name=torrent_name,
        )
    if btmh is not None:
        return TorrentIdentity(
            identity_kind=TorrentIdentityKind.BTMH,
            identity_value=btmh,
            btih=None,
            btmh=btmh,
            automation_eligible=False,
            torrent_name=torrent_name,
        )
    raise InvalidTorrent("unsupported_torrent_identity")
