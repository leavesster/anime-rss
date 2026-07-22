# Anime RSS Service

面向单用户、自托管场景的动画 RSS 获取与下载自动化服务。产品需求见 `DESIGN.md`；模块边界和依赖规则见 `ARCHITECTURE.md`；已实现行为和具体选择记录在 `IMPLEMENTATION.md`；首个版本的验收证据记录在 `ACCEPTANCE.md`。

## 当前实现状态

从订阅源到 qBittorrent 的产品链路和自托管交付层已经实现：

- FastAPI 应用及 SQLite/Alembic 运行时
- 加密存储订阅源 URL、请求头、magnet 链接和 torrent 载荷
- 有界 RSS/Atom 抓取、安全重定向处理和缓存验证器
- 持久化订阅源健康状态、重试状态、抓取历史和标准化条目
- 对 v1、混合型和纯 v2 种子的原始 bencode `info` 精确计算哈希
- 通过持久化集成事件实现跨订阅源发布资源去重
- 持久化调度器租约、执行历史、恢复和自动订阅源刷新
- 响应式 React 仪表盘、订阅源管理、抓取历史和发布资源库
- 生成 TypeScript API 类型并在生产环境提供静态资源
- 确定性标题识别和同集候选项分组
- 本地/Bangumi 动画目录及感知生命周期的订阅
- 确定性硬性过滤、有序偏好、备选等待和历史补全决策
- 加密的 qBittorrent 配置和连通性验证
- 幂等的 magnet/torrent 提交、任务对账同步和显式重试
- qBittorrent 4.6/5.x Web API 兼容性检查及两阶段删除确认
- 取消 V2/V3 任务时不删除已完成文件
- 依赖健康状态、失败工作汇总和仅追加审计历史
- 手动确认候选项及未匹配发布资源映射
- 首次运行管理员设置、Session Cookie 和受 CSRF 保护的修改操作
- 应用内通知，以及带持久化重试的加密 Webhook 投递
- 可移植的 SQLite 与主密钥备份、保留策略和重启安全的恢复暂存
- 串行化启动迁移，并在迁移前自动创建一致性备份
- 生产镜像、Compose 数据卷、就绪健康检查和非 root 运行时
- 带版本的实现决策记录，便于交接和审核
- 参考性播出日历、带版本的单集覆盖项、分集历史和一次性缺集警告

应用按单管理员、单进程设计。若要暴露到可信网络以外，请置于 HTTPS 后方；当 TLS 在服务源站终止时，设置 `ANIME_RSS_AUTH_COOKIE_SECURE=true`。默认支持使用 IP 地址和 `localhost` 访问。使用主机名或反向代理时，还必须声明浏览器信任边界：

```bash
ANIME_RSS_BROWSER_TRUSTED_HOSTS="anime.home,anime.example" \
ANIME_RSS_BROWSER_TRUSTED_ORIGINS="https://anime.example" \
ANIME_RSS_AUTH_COOKIE_SECURE=true \
docker compose up -d
```

可信主机是以逗号分隔的主机名，可以使用前置 `*.` 通配符。可信源是以逗号分隔的精确 HTTP(S) 源，非默认端口也必须包含在内。代理应保留原始 `Host` 请求头。业务命令执行前，服务会拒绝不可信 Host、跨源写入和跨站 Fetch Metadata。初始设置和登录按客户端地址限制为每 5 分钟 5 次；订阅源、qBittorrent 和 Webhook 连接测试限制为每分钟 10 次。由于服务不信任转发的客户端 IP 请求头，处于同一代理后的客户端会有意共享该代理对应的保守限流桶。

## Docker Compose

```bash
docker compose up -d --build
```

打开 `http://127.0.0.1:8080`，完成管理员设置。Compose 会把数据库、加密密钥、7 份滚动备份归档和 14 天的 JSONL 应用日志存储在 `anime-rss-data` 数据卷中。升级镜像时不要删除或重建该数据卷。

若要直接运行已发布镜像而不是在本地构建，请设置 `ANIME_RSS_IMAGE`：

```bash
ANIME_RSS_IMAGE=ghcr.io/OWNER/anime-rss-service:VERSION docker compose up -d
```

升级前，请通过系统页面或以下命令创建运维备份：

```bash
docker compose exec anime-rss anime-rss backup --data-dir /data
docker compose build --pull
docker compose up -d
docker compose ps
```

迁移会在 HTTP 服务和调度工作启动前运行。恢复和迁移操作通过操作系统文件锁串行化；Alembic 修改已有版本的数据库之前，会先创建一份 `pre-migration` 归档。全新安装和已使用当前 schema 的重启不会创建该归档。获取锁默认最多等待 60 秒，可以通过 `ANIME_RSS_MIGRATION_LOCK_TIMEOUT_SECONDS` 限制等待时间。

若要回滚应用数据，请在系统页面上传 `.backup` 归档并重启容器：

```bash
docker compose restart anime-rss
```

恢复归档包含主加密密钥，必须像凭据一样妥善保护。应用已暂存的恢复前，会先创建一份 `pre-restore` 归档。

## 开发

需要 Python 3.13。
前端开发需要 Node.js 22。

```bash
python3 -m venv .venv
make bootstrap
make bootstrap-web
make verify
make migrate
make run
```

使用 `make build-web` 构建 Web 应用。之后，后端会在 `http://127.0.0.1:8080` 同时提供界面和 API；OpenAPI 仍可通过 `/docs` 访问。前端开发期间，在第二个终端中运行 `make run-web` 并打开 `http://127.0.0.1:5173`；Vite 会把 API 调用代理到后端。运行时数据默认存放在 `./data`，并被 Git 忽略。

稳定的工程门禁通过 Makefile 对外提供，而不是隐藏在 CI 中：

```bash
make doctor
make openapi-check
make security-scan
make clean-room-acceptance
```

`doctor` 是只读安装检查，涵盖数据目录访问、SQLite 完整性和迁移 head、32 字节且权限为 `0600` 的主密钥、已暂存恢复状态，以及构建后的 Web 资源。`openapi-check` 会在临时目录中重新生成文件，只要任一受检生成物已过期就会失败。`security-scan` 审计已锁定的 Python 和 npm 依赖，并拒绝 Bandit 中等级别及以上的发现；它需要联网访问漏洞数据库。`clean-room-acceptance` 要求当前提交无未提交改动，然后创建分离的 worktree，重新安装 Python 和 npm 依赖，再执行验证、安全检查、Compose 生命周期测试和两个受支持的 qBittorrent 契约测试。

候选发布版本使用不可变的证据目录：

```bash
cp scripts/release-review-template.md release-review.md
# 完成七天浸泡测试后的三个审核项。
make release-evidence VERSION=0.1.0
make release-evidence-check VERSION=0.1.0
```

第一条命令会记录精确提交和自动化无污染环境日志，捕获已完成且脱敏的真实订阅源浸泡测试报告，并将已完成的手动审核封存在 `release-evidence/<version>/` 下。它拒绝生成不完整证据。检查器会拒绝校验和漂移、提交不一致、七天浸泡测试未完成、前置条件待处理、审核项未勾选或工作区不干净等情况。证据目录会被 Git 有意忽略，应随发布版本归档，而不能原地编辑。

修改镜像打包、迁移或备份行为前，请运行 `make acceptance-compose`。它会构建历史基线和当前镜像，然后使用一次性 Compose 项目验证全新设置、备份、原地升级、空数据卷恢复和基于备份的回滚。

修改下载器适配器后，请运行 `make acceptance-qbittorrent`。它使用按摘要固定的 qBittorrent 4.6.7 和 5.0.4 容器验证真实 Web API 契约。

容器发布受 amd64 和 arm64 两套独立镜像构建门禁约束。每个架构都必须从空数据卷启动，提供 SPA 和就绪端点，以非 root 用户通过容器内 doctor 检查，达到 Docker `healthy` 健康状态，并通过 Trivy 高危/严重漏洞扫描，之后才会推送多架构 manifest。已发布的摘要会附带 SBOM、来源证明和无密钥 Cosign 签名。Dependabot 每周提出 Python、npm、Docker 和 Actions 锁定版本更新。Dockerfile 和 qBittorrent 契约矩阵会保留可读的版本标签，同时按摘要固定多架构镜像索引。

真实订阅源发布验收使用 `make acceptance-soak-preflight`。当它报告两个健康订阅源、两个正在追踪的 Bangumi 动画、已验证的 qBittorrent 连接和健康调度器后，只运行一次 `make acceptance-soak-start`。`make acceptance-soak-status` 和 `make acceptance-soak-report` 可检查不可变的七天窗口，且不会暴露订阅源 URL 或下载器凭据。

## 已实现 API

```text
GET    /api/v1/health/live
GET    /api/v1/health/ready
GET    /api/v1/auth/status
POST   /api/v1/auth/setup
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
POST   /api/v1/feeds
GET    /api/v1/feeds
PATCH  /api/v1/feeds/{feed_id}
DELETE /api/v1/feeds/{feed_id}
POST   /api/v1/feeds/test
POST   /api/v1/feeds/{feed_id}/refresh
GET    /api/v1/feeds/{feed_id}/entries
GET    /api/v1/feeds/{feed_id}/fetches
GET    /api/v1/releases
GET    /api/v1/recognition/episode-groups
GET    /api/v1/recognition/unmatched
POST   /api/v1/recognition/candidates/{candidate_id}/confirm
POST   /api/v1/recognition/releases/{release_id}/remap
POST   /api/v1/recognition/releases/{release_id}/rerun
GET    /api/v1/catalog/anime
POST   /api/v1/catalog/anime
GET    /api/v1/catalog/bangumi/search
POST   /api/v1/catalog/bangumi/{bangumi_id}/import
PUT    /api/v1/catalog/anime/{anime_id}/schedule
GET    /api/v1/subscriptions
POST   /api/v1/subscriptions
PATCH  /api/v1/subscriptions/{subscription_id}
GET    /api/v1/subscriptions/preferences/global
PUT    /api/v1/subscriptions/preferences/global
GET    /api/v1/selection/episodes
GET    /api/v1/selection/decisions
POST   /api/v1/selection/process-due
GET    /api/v1/selection/subscriptions/{subscription_id}/backfill-preview
POST   /api/v1/selection/subscriptions/{subscription_id}/backfill-commit
POST   /api/v1/selection/subscriptions/{subscription_id}/candidates/{candidate_id}/select
POST   /api/v1/selection/subscriptions/{subscription_id}/candidates/{candidate_id}/reject
POST   /api/v1/selection/subscriptions/{subscription_id}/episodes/{episode_key}/reset
POST   /api/v1/selection/subscriptions/{subscription_id}/episodes/{episode_key}/acquired-elsewhere
GET    /api/v1/selection/manual-actions
GET    /api/v1/downloads/config
PUT    /api/v1/downloads/config
POST   /api/v1/downloads/config/test
GET    /api/v1/downloads/tasks
POST   /api/v1/downloads/tasks/{task_id}/retry
POST   /api/v1/downloads/process
GET    /api/v1/schedule/calendar
GET    /api/v1/schedule/missing
GET    /api/v1/schedule/anime/{anime_id}/episodes
GET    /api/v1/schedule/anime/{anime_id}/overrides
PUT    /api/v1/schedule/anime/{anime_id}/overrides/{episode_key}
DELETE /api/v1/schedule/anime/{anime_id}/overrides/{episode_key}
POST   /api/v1/schedule/sync
GET    /api/v1/operations/overview
GET    /api/v1/operations/jobs
GET    /api/v1/operations/runs
POST   /api/v1/operations/run-now
GET    /api/v1/notifications
POST   /api/v1/notifications/{notification_id}/read
GET    /api/v1/notifications/config
PUT    /api/v1/notifications/config
POST   /api/v1/notifications/config/test
GET    /api/v1/system/backups
POST   /api/v1/system/backups
GET    /api/v1/system/backups/{filename}
POST   /api/v1/system/backups/restore/stage
GET    /api/v1/system/settings
PUT    /api/v1/system/settings
GET    /api/v1/audit/events
```
