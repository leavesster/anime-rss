import { ArrowRight, Bell, Check, CheckCheck, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { Notification } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

type NotificationFilter = "unread" | "attention" | "all";

type NotificationGroup = {
  key: string;
  latest: Notification;
  items: Notification[];
  unreadIds: string[];
};

const objectLabels: Record<string, string> = {
  candidate: "候选版本",
  decision: "版本选择",
  download_task: "下载任务",
  expected_episode: "预期集数",
  feed: "订阅源",
  release: "发布条目",
};

const deliveryLabels: Record<string, string> = {
  delivered: "Webhook 已发送",
  delivering: "Webhook 发送中",
  failed: "Webhook 发送失败",
  pending: "Webhook 待发送",
  retrying: "Webhook 等待重试",
};

function actionFor(item: Notification): { label: string; to: string } | null {
  if (item.kind === "manual_confirmation" || item.kind === "release_mapping") {
    return { label: "处理识别", to: "/candidates" };
  }
  if (item.kind === "decision_committed") {
    return { label: "查看选择", to: "/candidates" };
  }
  if (item.kind.startsWith("feed_")) {
    return {
      label: "查看订阅源",
      to: item.entity_id ? `/feeds/${item.entity_id}` : "/feeds",
    };
  }
  if (item.kind === "episode_missing") {
    return { label: "查看追番", to: "/subscriptions" };
  }
  if (item.kind.startsWith("download_")) {
    return {
      label: item.level === "error" ? "处理下载" : "查看下载",
      to: "/downloads",
    };
  }
  return null;
}

function groupNotifications(items: Notification[]): NotificationGroup[] {
  const groups = new Map<string, Notification[]>();
  for (const item of items) {
    const entityKey = item.entity_id ? `${item.entity_type ?? "object"}:${item.entity_id}` : item.id;
    const key = `${item.kind}:${entityKey}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()].map(([key, groupedItems]) => ({
    key,
    latest: groupedItems[0],
    items: groupedItems,
    unreadIds: groupedItems.filter((item) => !item.read_at).map((item) => item.id),
  }));
}

export function NotificationQueue({
  items,
  isMarkingRead,
  isRefreshing,
  onMarkRead,
  onRefresh,
}: {
  items: Notification[];
  isMarkingRead: boolean;
  isRefreshing: boolean;
  onMarkRead: (ids: string[]) => void;
  onRefresh: () => void;
}) {
  const [filter, setFilter] = useState<NotificationFilter>("unread");
  const unreadItems = items.filter((item) => !item.read_at);
  const attentionItems = items.filter((item) => item.level === "warning" || item.level === "error");
  const visibleItems = useMemo(() => {
    if (filter === "unread") return items.filter((item) => !item.read_at);
    if (filter === "attention") return items.filter((item) => item.level === "warning" || item.level === "error");
    return items;
  }, [filter, items]);
  const groups = useMemo(() => groupNotifications(visibleItems), [visibleItems]);

  return (
    <section className="system-section system-section--wide">
      <div className="section-heading notification-heading">
        <div>
          <h2>消息队列</h2>
          <p>当前载入最近 {items.length} 条，{unreadItems.length} 条未读；导航数字采用相同口径</p>
        </div>
        <Button size="icon" variant="ghost" title="刷新消息" aria-label="刷新消息" icon={<RefreshCw className={isRefreshing ? "spin" : ""} size={16} />} disabled={isRefreshing} onClick={onRefresh} />
      </div>

      <div className="notification-toolbar">
        <div className="segmented" role="tablist" aria-label="消息筛选">
          <button className={filter === "unread" ? "segmented__active" : ""} role="tab" aria-selected={filter === "unread"} onClick={() => setFilter("unread")}>未读 <span>{unreadItems.length}</span></button>
          <button className={filter === "attention" ? "segmented__active" : ""} role="tab" aria-selected={filter === "attention"} onClick={() => setFilter("attention")}>需处理 <span>{attentionItems.length}</span></button>
          <button className={filter === "all" ? "segmented__active" : ""} role="tab" aria-selected={filter === "all"} onClick={() => setFilter("all")}>全部 <span>{items.length}</span></button>
        </div>
        <Button size="small" variant="ghost" icon={<CheckCheck size={15} />} title={`将当前载入的 ${unreadItems.length} 条未读消息标记为已读`} disabled={unreadItems.length === 0 || isMarkingRead} onClick={() => onMarkRead(unreadItems.map((item) => item.id))}>全部已读</Button>
      </div>

      {groups.length === 0 ? (
        <EmptyState
          icon={Bell}
          title={items.length === 0 ? "暂无消息" : filter === "unread" ? "没有未读消息" : filter === "attention" ? "没有需要处理的消息" : "暂无消息"}
          description={items.length === 0 ? "自动选择、下载和运行异常会显示在这里。" : "可以切换筛选查看其他消息。"}
        />
      ) : (
        <div className="notification-list">
          {groups.map((group) => {
            const item = group.latest;
            const action = actionFor(item);
            const objectLabel = item.entity_type ? objectLabels[item.entity_type] ?? "业务对象" : "系统";
            const deliveryLabel = item.delivery_state ? deliveryLabels[item.delivery_state] ?? "Webhook 状态未知" : null;
            return (
              <article className={group.unreadIds.length ? "notification-row notification-row--unread" : "notification-row"} key={group.key}>
                <span className={`notification-level notification-level--${item.level}`} />
                <div className="notification-copy">
                  <div className="notification-title"><strong>{item.title}</strong>{group.items.length > 1 && <span>同类 {group.items.length} 条</span>}</div>
                  <p>{item.message}</p>
                  <small>对象：{objectLabel} · {formatDate(item.created_at)}{deliveryLabel ? ` · ${deliveryLabel}` : ""}</small>
                </div>
                <StatusBadge status={group.unreadIds.length ? "unread" : "read"} />
                <div className="notification-actions">
                  {action && <Link className="button button--secondary button--small" to={action.to}>{action.label}<ArrowRight size={14} /></Link>}
                  {group.unreadIds.length > 0 && <Button size="icon" variant="ghost" aria-label={`将“${item.title}”标记为已读`} title="标记同组消息为已读" icon={<Check size={16} />} disabled={isMarkingRead} onClick={() => onMarkRead(group.unreadIds)} />}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
