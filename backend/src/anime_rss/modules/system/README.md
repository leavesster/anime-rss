# System module

Owns installation-wide configuration, administrator sessions, cryptographic
secret handling, and portable backup/restore archives. Other modules may use
the `SecretCipher` public port but must never read the master key or persist
plaintext credentials.

## Public surface

- `SecretCipher.encrypt` and `SecretCipher.decrypt`
- `SecretCipher.blind_index` for purpose-bound deterministic secret comparison
- `FileSecretCipher.load_or_create`
- `AuthService` first-run setup, login, logout, and session validation
- `BackupService` online SQLite backup, retention, restore staging, and startup apply
- `StartupService` restore/migration serialization and pre-migration backup orchestration
- `InstanceSettingsService` timezone, interface language, missing grace, and setup progress
- Guided setup uses eight fixed, idempotent step IDs; completion is true only when all exist.

## Invariants

- New and reset passwords use Argon2id with 64 MiB memory, three iterations,
  one lane, a 32-byte hash, and a 16-byte salt. A valid legacy `scrypt-v1`
  password is upgraded in the successful login transaction without changing
  `password_changed_at`; the upgrade emits `system.password_hash_upgraded`.
- Session and CSRF values are stored only as hashes.
- Mutating authenticated HTTP requests require a matching CSRF cookie and header.
- A restore is validated and staged while live, then applied before migrations on restart.
- Restore and Alembic work share an OS-released file lock next to the database.
- A versioned database is backed up consistently before any pending migration;
  clean installs and already-current databases do not create migration backups.
- Backup archives include the master key and are therefore sensitive credentials.
- Instance-setting updates use optimistic versions and validated IANA timezones.
- Creating the administrator and recording the first setup step share one transaction.

## Does not own

- Feed health or HTTP behavior
- qBittorrent configuration semantics
- Domain decisions
