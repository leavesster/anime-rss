# System module

Owns installation-wide configuration, administrator sessions, cryptographic
secret handling, and portable backup/restore archives. Other modules may use
the `SecretCipher` public port but must never read the master key or persist
plaintext credentials.

## Public surface

- `SecretCipher.encrypt` and `SecretCipher.decrypt`
- `FileSecretCipher.load_or_create`
- `AuthService` first-run setup, login, logout, and session validation
- `BackupService` online SQLite backup, retention, restore staging, and startup apply
- `InstanceSettingsService` timezone, interface language, missing grace, and setup progress
- Guided setup uses eight fixed, idempotent step IDs; completion is true only when all exist.

## Invariants

- Passwords use salted scrypt; session and CSRF values are stored only as hashes.
- Mutating authenticated HTTP requests require a matching CSRF cookie and header.
- A restore is validated and staged while live, then applied before migrations on restart.
- Backup archives include the master key and are therefore sensitive credentials.
- Instance-setting updates use optimistic versions and validated IANA timezones.
- Creating the administrator and recording the first setup step share one transaction.

## Does not own

- Feed health or HTTP behavior
- qBittorrent configuration semantics
- Domain decisions
