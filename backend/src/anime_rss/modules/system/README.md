# System module

Owns installation-wide configuration and cryptographic secret handling. Other
modules may use the `SecretCipher` public port but must never read the master key
or persist plaintext credentials.

## Public surface

- `SecretCipher.encrypt` and `SecretCipher.decrypt`
- `FileSecretCipher.load_or_create`

## Does not own

- Feed health or HTTP behavior
- qBittorrent configuration semantics
- Domain decisions
