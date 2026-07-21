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
};

export function statusLabel(status: string): string {
  return labels[status] ?? status.replaceAll("_", " ");
}

export function statusTone(status: string): StatusTone {
  if (["healthy", "success", "ready", "resolved", "strong", "following", "decided"].includes(status)) return "positive";
  if (status === "high") return "positive";
  if (["auth_failed", "failed", "failing"].includes(status)) return "danger";
  if (["never_fetched", "pending", "weak", "medium", "low", "waiting_fallback", "needs_confirmation"].includes(status)) return "warning";
  if (["not_modified"].includes(status)) return "info";
  return "neutral";
}
