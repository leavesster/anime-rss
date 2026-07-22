# 发布资源模块

负责规范的 BitTorrent 发布资源标识，以及订阅源条目到该标识的关联。它通过幂等处理器消费 `FeedEntryObserved.v1`。

## 公共接口

- `ReleaseService.observe_feed_entry`
- `ReleaseService.list_releases`
- `ReleaseService.has_release`
- `ReleaseService.get_download_source`
- `ReleaseService.prune_unmatched`
- `parse_magnet_identity`
- `parse_torrent_identity`

## 不变量

- 优先使用 BitTorrent v1 info hash 作为全局标识。
- SHA-1/SHA-256 必须根据原始 bencode `info` 字节切片精确计算；解码后的字典绝不能重新编码后再计算哈希。
- 系统会收集纯 BitTorrent v2 发布资源，但不允许其参与自动化流程。
- `(identity_kind, identity_value)` 和 `(release_id, feed_entry_id)` 均保持唯一。
- 存储的 magnet 链接和 torrent 载荷均经过加密。
- 只有当筛选决策和识别模块的公共查询都未保护某个旧发布资源标识时，才能删除它。

## 不负责

- 订阅源配置或重试健康状态
- 动画标题解析
- 候选项或下载筛选决策
