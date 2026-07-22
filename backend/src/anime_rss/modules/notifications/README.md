# 通知模块

负责应用内通知事实和外部投递尝试。它消费集成事件，绝不参与筛选决策。

## 公共接口

- `NotificationService.handle_event`
- `NotificationService.list_notifications`
- `NotificationService.process_deliveries`
- `NotificationService.configure`

## 不变量

- 每个来源事件只创建一条通知。
- Webhook 凭据加密存储，且 API 永不返回这些凭据。
- 投递按通知 ID 保证幂等，并采用有界重试。
- 投递失败不能回滚或改变产生该通知的业务操作。
- 每个预期集数来源事件只展示一次 `EpisodeMissing.v1`。
