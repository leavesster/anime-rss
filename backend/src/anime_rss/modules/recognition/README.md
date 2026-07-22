# 识别模块

负责确定性的解析尝试和分集候选项投影视图。它消费 `ReleaseIdentified.v1`，并且只能通过 `releases.api` 公共契约读取发布资源观测数据。

## 公共接口

- `RecognitionService.handle_release_identified`
- `RecognitionService.list_episode_groups`
- `RecognitionService.list_unmatched`
- `RecognitionService.confirm_candidate`
- `RecognitionService.remap_release`
- `RecognitionService.rerun_release`
- `RecognitionService.permanent_release_ids`
- `parse_release_title`

## 不变量

- 解析器输出由标题和 `PARSER_VERSION` 共同决定。
- 带版本的夹具契约将扩充到至少 300 个完整黄金用例；确定性的 Unicode 属性用例在不依赖网络数据的情况下验证标准化、输出边界和可重复性。
- 集数使用规范化十进制字符串，绝不使用浮点数。
- 系列键经过大小写折叠后必须符合 300 字符的持久化上限，修订版号最多三位。
- 一个发布资源只能有一个活跃候选项；重新映射会取代旧候选项，而不是改写旧记录。
- 系列分组使用精确的标准化键；禁止模糊匹配。
- 每次来源观测都会生成一次不可变的初始解析尝试；显式重新运行解析器时，会追加具有独立标识的尝试，包括相同版本的重复运行。
- 输出不变的重新运行会保留活跃候选项。若输出发生变化且结构有效、置信度为中或高，则取代原候选项；低置信度输出绝不会移除有效的活跃候选项。
- 手动确认和发布资源映射会追加操作记录，绝不改写需要人工介入的解析尝试。
- 已被取代的候选项仍可供历史决策引用，但不会出现在当前分组和自动筛选决策查询中。
- 经手动确认或修正的发布资源指纹会永久受到保护，不会被未匹配发布资源的保留策略清理。

## 不负责

- 动画元数据或别名
- 订阅规则
- 候选项排序或下载决策
- qBittorrent 状态
