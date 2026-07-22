# 系统模块

负责整个安装实例的配置、管理员会话、加密密钥处理，以及可移植的备份与恢复归档。其他模块可以使用 `SecretCipher` 公共端口，但绝不能读取主密钥或持久化明文凭据。

## 公共接口

- `SecretCipher.encrypt` 和 `SecretCipher.decrypt`
- `SecretCipher.blind_index`：用于按用途隔离的确定性密文比较
- `FileSecretCipher.load_or_create`
- `AuthService`：初始设置、登录、退出和会话验证
- `BackupService`：在线 SQLite 备份、保留、恢复暂存和启动时应用
- `StartupService`：恢复与迁移的串行化，以及迁移前备份编排
- `InstanceSettingsService`：时区、界面语言、缺集宽限时间和设置进度
- 引导式设置使用八个固定且幂等的步骤 ID；只有全部步骤都存在时才算完成。

## 不变量

- 新密码和重置后的密码使用 Argon2id：64 MiB 内存、三次迭代、单通道、32 字节哈希和 16 字节盐。有效的旧版 `scrypt-v1` 密码会在登录成功的事务中升级，且不修改 `password_changed_at`；升级会发出 `system.password_hash_upgraded`。
- Session 和 CSRF 值只以哈希形式存储。
- 已认证的 HTTP 修改请求必须同时携带相匹配的 CSRF Cookie 和请求头。
- 恢复归档在服务运行时完成验证和暂存，重启后会在迁移前应用。
- 恢复操作和 Alembic 共用数据库旁边由操作系统释放的文件锁。
- 任何待执行迁移开始前，系统都会一致性备份已有版本的数据库；全新安装和已经是当前版本的数据库不会创建迁移备份。
- 备份归档包含主密钥，因此属于敏感凭据。
- 实例设置更新使用乐观版本控制，并验证 IANA 时区。
- 创建管理员和记录第一个设置步骤在同一事务中完成。

## 不负责

- 订阅源健康状态或 HTTP 行为
- qBittorrent 配置语义
- 领域决策
