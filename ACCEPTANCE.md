# 首个版本验收证据

本文档跟踪 `DESIGN.md` 中的 12 项发布标准。只有当所述证据真正覆盖对应边界时，标准才能标记为已验证。只要还有任意一项待处理，发布就仍未完成。

最后审核日期：2026-07-22。

| # | 标准 | 自动化或容器证据 | 真实系统证据 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 全新 Compose 设置 | `make acceptance-compose` 在历史镜像中完成全部八个设置步骤，并在升级后成功登录。 | 除一次性容器运行外，无需其他证据。 | 已验证 |
| 2 | 两个订阅源可可靠刷新 | 订阅源刷新、缓存、重试和调度器集成测试通过。 | 当前预检：一个订阅源中有一个健康；还需要第二个真实订阅源。 | 待处理 |
| 3 | 已订阅两个正在播出的 Bangumi 动画 | Bangumi 搜索、缓存、导入、播出计划和订阅集成测试通过。 | 当前预检：正在追踪的订阅中有 Bangumi 标识的数量为零；需要两个。 | 待处理 |
| 4 | 首选、备选和被拒绝的发布资源结果不同 | 筛选决策领域测试和订阅筛选集成测试覆盖全部三种结果及其解释。 | 浸泡测试报告会记录决策以供审核。 | 已验证 |
| 5 | 备选等待可跨重启保留 | `test_fallback_deadline_survives_and_commits_when_due` 在持久化截止时间后重启应用。 | 浸泡测试报告会标记丢失的已选决策。 | 已验证 |
| 6 | 多个订阅源发现同一发布资源时只提交一次 | `test_same_release_from_two_feeds_is_stored_once` 和“成功后超时”下载测试共同证明发布资源及提交的幂等性。 | 浸泡测试报告会统计跨订阅源发布资源和重复下载标识。 | 已验证 |
| 7 | qBittorrent 停机后恢复且不重复提交 | 下载集成测试覆盖瞬时失败、重试前查询、提交中断恢复和显式重试。 | 开始浸泡测试前必须连接 qBittorrent。 | 已验证 |
| 8 | 一次别名修正会影响后续匹配 | `test_manual_alias_correction_matches_later_entries` 证明：显式更新订阅别名后，新条目可以成功匹配，且不会改写之前未匹配的条目。 | 手动映射和筛选操作会被计数以供审核。 | 已验证 |
| 9 | V2 替换未完成任务且不删除旧文件 | `test_upgrade_cancels_incomplete_task_without_deleting_files` 断言 `deleteFiles=false`、持久化取代关系、先删后加的顺序和新任务提交。 | 真实的 4.6.7 与 5.0.4 契约验收会执行未完成任务取消。 | 已验证 |
| 10 | 尊重 qBittorrent 外部删除 | `test_config_submit_reconcile_external_delete_and_explicit_retry` 要求连续两次成功的空查询，在查询失败后重置确认状态，并证明显式重试前不会自动重新添加。 | 浸泡测试报告会显示未解决的下载器状态。 | 已验证 |
| 11 | 全新恢复会保留持久化关联 | `make acceptance-compose` 验证原地升级、全新恢复及回滚后仍保留设置、审计历史、等待中的作业、订阅/订阅源数据，以及 Decision 与 DownloadTask 关联。 | 除一次性容器运行外，无需其他证据。 | 已验证 |
| 12 | 连续七天真实订阅源运行无错误匹配、重复或状态丢失 | 浸泡工具会拒绝不完整预检，记录不可变的开始状态，并在七天边界报告完整性信号。 | 需要七个自然日以及手动映射审核。 | 待处理 |

## 浸泡测试流程

针对持久化数据目录运行预检：

```bash
make acceptance-soak-preflight
```

预检要求：设置已完成、至少两个订阅源健康、两个带 Bangumi 标识的追踪中订阅、qBittorrent 连接测试成功，以及调度器健康。所有检查通过后，只启动一次：

```bash
make acceptance-soak-start
```

开始标记不可变，存储在 `data/acceptance/real-feed-soak.json`。再次运行 `start` 会返回原始窗口。同一数据卷上的进程或容器重启不会影响该标记。运维备份归档不会包含它；恢复到空数据卷后必须重新开始一个七天窗口。

可随时检查进度或渲染当前 Markdown 证据：

```bash
make acceptance-soak-status
make acceptance-soak-report
```

`duration_met` 仅表示已经过七个自然日。最终批准仍需审核动画和集数映射、手动修正，以及实际 qBittorrent 任务列表。汇总计数无法证明语义匹配的质量。

## 发布证据门禁

标准 12 达到七天边界后，将 `scripts/release-review-template.md` 复制到被忽略的 `release-review.md`，完成全部三项检查，然后运行：

```bash
make release-evidence VERSION=<semver>
make release-evidence-check VERSION=<semver>
```

创建证据前，如果浸泡测试仍待处理或手动审核未完成，命令会拒绝继续运行隔离的自动化测试套件。最终目录会记录精确的 Git 修订版本，并为无污染环境日志、本文档、脱敏的浸泡测试报告和已完成审核计算校验和。该版本对应的证据目录不可变。
