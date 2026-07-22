# 部署与开发

本文档说明 Anime RSS Service 的安装、首次配置、升级恢复、网络安全设置和本地开发流程。产品功能介绍见[项目 README](../README.md)。

## Docker Compose 部署

项目默认从本地源码构建镜像：

```bash
docker compose up -d --build
```

打开 <http://127.0.0.1:8080>。首次访问没有预设账号或默认密码，页面会引导你创建管理员并完成初始配置：

1. 选择实例时区和下载默认值。
2. 填写 qBittorrent Web API 地址并测试连接。
3. 添加至少一个 RSS/Atom 订阅源。
4. 导入或创建动画，设置版本偏好，然后建立追番。
5. 在候选预览中确认识别和筛选结果，再让调度器持续运行。

Compose 会把 SQLite 数据库、主加密密钥、滚动备份和应用日志保存在 `anime-rss-data` 数据卷中。升级或重建容器时不要删除这个数据卷。

## 升级与恢复

升级前，可以在系统页面创建备份，也可以执行：

```bash
docker compose exec anime-rss anime-rss backup --data-dir /data
docker compose build --pull
docker compose up -d
docker compose ps
```

数据库迁移会在 HTTP 服务和后台调度器启动前自动完成。修改已有数据库前，服务会先创建一致的 `pre-migration` 备份；迁移、备份恢复和启动过程使用文件锁串行化，避免多个进程同时修改数据。

若要恢复，在系统页面上传 `.backup` 归档后重启容器：

```bash
docker compose restart anime-rss
```

备份归档同时包含数据库和主加密密钥，必须像凭据一样保护。应用正式执行已暂存的恢复前，还会先创建一份 `pre-restore` 归档。

## 域名与反向代理

默认配置适合通过 `localhost` 或 IP 地址在可信网络内访问。通过域名或反向代理部署时，需要声明允许的主机和浏览器来源；暴露到可信网络之外时，应使用 HTTPS：

```bash
ANIME_RSS_BROWSER_TRUSTED_HOSTS="anime.home,anime.example" \
ANIME_RSS_BROWSER_TRUSTED_ORIGINS="https://anime.example" \
ANIME_RSS_AUTH_COOKIE_SECURE=true \
docker compose up -d
```

`ANIME_RSS_BROWSER_TRUSTED_HOSTS` 接受逗号分隔的主机名和前置 `*.` 通配符。`ANIME_RSS_BROWSER_TRUSTED_ORIGINS` 必须填写完整 HTTP(S) 来源，非默认端口也要包含在内。反向代理需要保留原始 `Host` 请求头。

服务会在业务操作前拒绝不可信 Host、跨源写入和跨站请求。初始设置和登录按客户端地址限制为每 5 分钟 5 次；订阅源、qBittorrent 和 Webhook 连接测试限制为每分钟 10 次。服务不信任转发的客户端 IP 请求头，因此同一代理后的客户端会共享限流额度。

## 本地开发

后端需要 Python 3.13，前端需要 Node.js 22：

```bash
python3 -m venv .venv
make bootstrap
make bootstrap-web
make verify
make migrate
make run
```

`make run` 在 <http://127.0.0.1:8080> 提供 API 和已构建的前端，OpenAPI 文档位于 <http://127.0.0.1:8080/docs>。前端开发时，在另一个终端运行 `make run-web` 并打开 <http://127.0.0.1:5173>；Vite 会把 API 请求代理到后端。

## 工程检查

```bash
make doctor
make openapi-check
make security-scan
make acceptance-compose
make acceptance-qbittorrent
```

`make doctor` 只读检查数据目录、SQLite 完整性、迁移版本、主密钥、暂存恢复和前端资源。`make openapi-check` 验证生成的 OpenAPI 与 TypeScript 类型没有过期。`make security-scan` 检查 Python 和 npm 依赖以及后端代码；该命令需要联网获取漏洞数据。

`make acceptance-compose` 验证全新安装、备份、原地升级、空数据卷恢复和基于备份的回滚。`make acceptance-qbittorrent` 使用真实容器验证 qBittorrent 4.6.7 和 5.0.4 的 Web API 契约。

## 延伸文档

- [产品设计](../DESIGN.md)：目标用户、产品边界和完整业务规则。
- [系统架构](../ARCHITECTURE.md)：模块职责、依赖方向和持久化工作流。
- [实现记录](../IMPLEMENTATION.md)：当前代码已经实现的行为与技术决策。
- [验收记录](../ACCEPTANCE.md)：首个发布版本的验收范围和证据要求。
