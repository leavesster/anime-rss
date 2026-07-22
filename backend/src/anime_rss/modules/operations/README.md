# 运维模块

负责通用的持久化作业和工作器租约。业务截止时间仍由相应业务模块负责；作业只在截止时间到达时调用公共命令。

## 公共接口

- `JobService.ensure_job`
- `JobService.synchronize_job`
- `JobService.claim_due`
- `JobService.complete`
- `JobService.reschedule`
- `JobService.list_jobs`
- `JobService.list_runs`
- `JobService.prune_run_history`
- `Scheduler.run_once`

## 不变量

- `(job_kind, dedupe_key)` 保持唯一。
- 任务领取使用条件更新，因此重叠的工作器无法同时获得同一份未过期租约。
- 作业载荷带有版本，且不包含凭据。
- 每次已领取的执行都有一条仅追加的运行记录。
- 租约过期后，中断的运行可在重启后恢复。
- 业务模块负责的截止时间可以替换排队中的到期时间；通用周期性作业则保留工作器重新安排的到期时间。
- 每次执行都会获得新的关联 ID，并以作业 ID 作为因果 ID。
- 每日保留作业只协调各模块公共 API，并在普通作业运行详情中记录数量。

## 不负责

- 订阅源重试策略或下次抓取状态
- 筛选决策备选方案的截止时间
- 预期集数和缺集状态的评估
- 下载重试和对账同步状态
- 跨模块业务失败状态
