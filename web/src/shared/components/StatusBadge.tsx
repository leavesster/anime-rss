import { statusLabel, statusTone } from "../lib/status";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status status--${statusTone(status)}`}>{statusLabel(status)}</span>;
}
