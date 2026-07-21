export type StatusTone = "positive" | "warning" | "danger" | "neutral" | "info";

const labels: Record<string, string> = {
  healthy: "正常",
  success: "成功",
  ready: "就绪",
  never_fetched: "待首次抓取",
  not_modified: "无更新",
  auth_failed: "认证失败",
  failing: "抓取异常",
  failed: "失败",
  pending: "处理中",
  strong: "已识别",
  weak: "弱标识",
  resolved: "已解析",
  unresolved: "待解析",
  high: "高置信",
  medium: "中置信",
  low: "低置信",
  following: "追番中",
  paused: "已暂停",
  completed: "已完结",
  archived: "已归档",
  decided: "已决定",
  waiting_fallback: "等待备选",
  needs_confirmation: "需要确认",
  planned: "等待提交",
  retrying: "等待重试",
  submitting: "正在提交",
  submitted: "等待确认",
  downloading: "下载中",
  externally_removed: "外部删除",
  canceling: "正在替换",
  superseded: "已被替代",
  connected: "已连接",
  idle: "空闲",
  running: "运行中",
  degraded: "异常",
  starting: "启动中",
  on_demand: "按需连接",
  not_configured: "未配置",
  unknown: "待检查",
  recovered: "已恢复",
  error: "错误",
  warning: "提醒",
  info: "信息",
  scheduled: "待播出",
  acquired: "已获取",
  missing: "缺集",
  inactive: "非当前周期",
};

export function statusLabel(status: string): string {
  return labels[status] ?? status.replaceAll("_", " ");
}

export function statusTone(status: string): StatusTone {
  if (["healthy", "success", "ready", "resolved", "strong", "following", "decided", "completed", "connected", "idle", "recovered", "acquired"].includes(status)) return "positive";
  if (status === "high") return "positive";
  if (["auth_failed", "failed", "failing", "externally_removed", "degraded", "error", "missing"].includes(status)) return "danger";
  if (["never_fetched", "pending", "weak", "medium", "low", "waiting_fallback", "needs_confirmation", "retrying", "submitting", "submitted", "canceling", "starting", "unknown", "warning"].includes(status)) return "warning";
  if (["not_modified", "planned", "downloading", "running", "on_demand", "not_configured", "info"].includes(status)) return "info";
  return "neutral";
}
