import base64
import hashlib

import pytest
from anime_rss.modules.releases.domain import (
    InvalidTorrent,
    TorrentIdentityKind,
    parse_magnet_identity,
    parse_torrent_identity,
)


def _v1_torrent() -> tuple[bytes, bytes]:
    info = b"d4:name4:Test12:piece lengthi16384e6:pieces20:" + (b"x" * 20) + b"e"
    return b"d8:announce14:https://t.test4:info" + info + b"e", info


def test_hex_and_base32_magnets_normalize_to_same_btih() -> None:
    raw_hash = bytes.fromhex("0123456789abcdef0123456789abcdef01234567")
    hexadecimal = raw_hash.hex()
    encoded = base64.b32encode(raw_hash).decode()

    first = parse_magnet_identity(f"magnet:?xt=urn:btih:{hexadecimal}&tr=https://secret")
    second = parse_magnet_identity(f"magnet:?xt=urn:btih:{encoded}")

    assert first == second
    assert first.identity_kind is TorrentIdentityKind.BTIH
    assert first.automation_eligible


def test_magnet_extracts_and_normalizes_torrent_name() -> None:
    identity = parse_magnet_identity(
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=%5BGroup%5D++Anime+01.mkv"
    )

    assert identity.torrent_name == "[Group] Anime 01.mkv"


def test_torrent_hash_uses_exact_raw_info_slice() -> None:
    payload, raw_info = _v1_torrent()

    identity = parse_torrent_identity(payload)

    assert identity.btih == hashlib.sha1(raw_info, usedforsecurity=False).hexdigest()
    assert identity.identity_value == identity.btih
    assert identity.automation_eligible
    assert identity.torrent_name == "Test"


def test_torrent_prefers_utf8_name() -> None:
    utf8_name = "动画 01.mkv".encode()
    info = (
        b"d4:name8:fallback10:name.utf-8"
        + str(len(utf8_name)).encode()
        + b":"
        + utf8_name
        + b"12:piece lengthi16384e6:pieces20:"
        + (b"x" * 20)
        + b"e"
    )

    identity = parse_torrent_identity(b"d4:info" + info + b"e")

    assert identity.torrent_name == "动画 01.mkv"


def test_pure_v2_is_identified_but_not_automation_eligible() -> None:
    info = b"d9:file treede12:meta versioni2e4:name4:Test12:piece lengthi16384ee"
    payload = b"d4:info" + info + b"e"

    identity = parse_torrent_identity(payload)

    assert identity.identity_kind is TorrentIdentityKind.BTMH
    assert identity.btmh == "1220" + hashlib.sha256(info).hexdigest()
    assert not identity.automation_eligible


@pytest.mark.parametrize(
    "payload,error_code",
    [
        (b"", "torrent_payload_size_invalid"),
        (b"d3:fooi1ee", "missing_info_dictionary"),
        (b"d4:infod4:name4:Testeejunk", "trailing_bencode_data"),
        (b"d4:infod4:name4:Teste4:infoi1ee", "duplicate_bencode_key"),
    ],
)
def test_invalid_torrent_is_rejected(payload: bytes, error_code: str) -> None:
    with pytest.raises(InvalidTorrent, match=error_code):
        parse_torrent_identity(payload)
