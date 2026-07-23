import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Notification } from "../src/generated/api/client";
import { NotificationQueue } from "../src/features/system/NotificationQueue";

afterEach(cleanup);

function notification(overrides: Partial<Notification> & Pick<Notification, "id" | "kind" | "level" | "title">): Notification {
  return {
    message: "消息内容",
    entity_type: null,
    entity_id: null,
    read_at: null,
    delivery_state: null,
    delivery_error_code: null,
    created_at: "2026-07-23T00:00:00Z",
    ...overrides,
  };
}

describe("notification queue", () => {
  it("groups repeated object messages and exposes the matching action", () => {
    const onMarkRead = vi.fn();
    const items = [
      notification({ id: "feed-new", kind: "feed_failure", level: "error", title: "订阅源连续抓取失败", entity_type: "feed", entity_id: "feed-1", delivery_state: "retrying" }),
      notification({ id: "feed-old", kind: "feed_failure", level: "error", title: "订阅源连续抓取失败", entity_type: "feed", entity_id: "feed-1" }),
      notification({ id: "missing", kind: "episode_missing", level: "warning", title: "预期集数仍未出现", entity_type: "expected_episode", entity_id: "episode-1" }),
      notification({ id: "complete", kind: "download_completed", level: "success", title: "下载已完成", entity_type: "download_task", entity_id: "task-1", read_at: "2026-07-23T00:10:00Z" }),
    ];

    render(
      <MemoryRouter>
        <NotificationQueue items={items} isMarkingRead={false} isRefreshing={false} onMarkRead={onMarkRead} onRefresh={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText("同类 2 条")).toBeInTheDocument();
    expect(screen.getByText(/对象：订阅源/)).toBeInTheDocument();
    expect(screen.getByText(/Webhook 等待重试/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看订阅源" })).toHaveAttribute("href", "/feeds/feed-1");
    expect(screen.queryByText("下载已完成")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "将“订阅源连续抓取失败”标记为已读" }));
    expect(onMarkRead).toHaveBeenCalledWith(["feed-new", "feed-old"]);

    fireEvent.click(screen.getByRole("button", { name: "全部已读" }));
    expect(onMarkRead).toHaveBeenLastCalledWith(["feed-new", "feed-old", "missing"]);
  });

  it("filters attention items separately from read state", () => {
    const items = [
      notification({ id: "complete", kind: "download_completed", level: "success", title: "下载已完成", entity_type: "download_task", entity_id: "task-1", read_at: "2026-07-23T00:10:00Z" }),
      notification({ id: "failed", kind: "download_failed", level: "error", title: "下载任务需要处理", entity_type: "download_task", entity_id: "task-2", read_at: "2026-07-23T00:11:00Z" }),
    ];

    render(
      <MemoryRouter>
        <NotificationQueue items={items} isMarkingRead={false} isRefreshing={false} onMarkRead={vi.fn()} onRefresh={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText("没有未读消息")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /需处理/ }));
    expect(screen.getByText("下载任务需要处理")).toBeInTheDocument();
    expect(screen.getByText("已读")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "处理下载" })).toHaveAttribute("href", "/downloads");
    expect(screen.queryByText("下载已完成")).not.toBeInTheDocument();
  });
});
