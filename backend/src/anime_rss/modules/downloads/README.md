# 下载模块

负责加密的 qBittorrent 配置、持久化下载任务、提交尝试、幂等键、取消请求，以及观测到的下载器状态。

公共接口：

- `DownloadService`：对外提供配置、意图规划、重试和查询能力。
- `DownloadWorker`：内部的提交、取消、恢复和对账同步循环。
- `Downloader` 及查询端口：隔离外部副作用和来源 DTO 的依赖边界。
- `QbittorrentClient`：实现产品级 `Downloader` 端口的适配器。
- `/api/v1/downloads`：配置、连通性、任务、重试和同步 API。

本模块通过公共模块 API 使用发布资源载荷和订阅保存路径 DTO。它绝不决定由哪个候选项胜出，也绝不修改筛选决策历史。订阅保存路径优先于实例默认值；否则，新任务在规划时会捕获当时配置的默认路径、分类和标签。

每个任务都有且只有一个明确且不可变的来源：`selection_decision` 任务引用一个 Decision 和 Subscription，`manual_release` 任务两者都不引用。手动提交发布资源要求先保存 qBittorrent 配置；配置存在但下载器暂时离线时仍可持久化排队。提交时会复用同一 Release 的现有任务；所有网络调用之前先记录意图，然后沿用自动下载所使用的工作器和 info hash 对账同步流程。

`DownloadService.retained_release_ids` 还会保护任务历史所引用的 Release 载荷，防止它们被未匹配条目的保留策略清理。

## 兼容性

- 适配器支持 qBittorrent `>=4.6.0,<6.0.0`，且要求 Web API 主版本为 2。
- 连接测试会查询并返回应用版本和 Web API 版本。
- `make acceptance-qbittorrent` 会让生产适配器连接固定的真实容器 `4.6.7 / 2.9.3` 和 `5.0.4 / 2.11.2`，验证添加、查询及未完成任务取消流程。

## 对账同步不变量

- 对已观测任务进行一次成功的空查询，只会将其标记为未确认和过期；仅当连续第二次成功查询仍为空时，才会变为 `externally_removed`。查询失败或查询到任务都会重置计数。
- 替换任务在其前序任务已持久化取消或完成状态、且 `superseded_at` 已设置之前，一直保持 planned 状态。
- 取消操作始终使用 `deleteFiles=false`。
