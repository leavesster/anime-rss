const relativeFormatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatDate(value: string | null | undefined): string {
  if (!value) return "尚无记录";
  return dateFormatter.format(new Date(value));
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "尚无记录";
  const delta = new Date(value).getTime() - Date.now();
  const abs = Math.abs(delta);
  if (abs < 60_000) return relativeFormatter.format(Math.round(delta / 1_000), "second");
  if (abs < 3_600_000) return relativeFormatter.format(Math.round(delta / 60_000), "minute");
  if (abs < 86_400_000) return relativeFormatter.format(Math.round(delta / 3_600_000), "hour");
  return relativeFormatter.format(Math.round(delta / 86_400_000), "day");
}

export function formatInterval(seconds: number): string {
  return `${Math.round(seconds / 60)} 分钟`;
}

export function truncateHash(value: string): string {
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-7)}` : value;
}
