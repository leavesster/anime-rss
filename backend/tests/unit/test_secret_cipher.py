import pytest
from anime_rss.modules.system.api import AesGcmSecretCipher
from cryptography.exceptions import InvalidTag


def test_secret_cipher_round_trip_is_bound_to_purpose() -> None:
    cipher = AesGcmSecretCipher(b"k" * 32)
    envelope = cipher.encrypt(b"private-token", purpose="feed:one:endpoint")

    assert b"private-token" not in envelope
    assert cipher.decrypt(envelope, purpose="feed:one:endpoint") == b"private-token"
    assert cipher.blind_index(b"private-token", purpose="feed:endpoint") == cipher.blind_index(
        b"private-token", purpose="feed:endpoint"
    )
    assert cipher.blind_index(b"other-token", purpose="feed:endpoint") != cipher.blind_index(
        b"private-token", purpose="feed:endpoint"
    )
    with pytest.raises(InvalidTag):
        cipher.decrypt(envelope, purpose="feed:two:endpoint")
