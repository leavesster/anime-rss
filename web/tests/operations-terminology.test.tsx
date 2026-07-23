import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OperationsPage } from "../src/features/operations/OperationsPage";
import {
  getOperationsOverview,
  listAuditEvents,
  listJobRuns,
  listScheduledJobs,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  getOperationsOverview: vi.fn(),
  listAuditEvents: vi.fn(),
  listJobRuns: vi.fn(),
  listScheduledJobs: vi.fn(),
  runSchedulerNow: vi.fn(),
}));

describe("operations terminology", () => {
  it("describes scheduled work without persistence and lease jargon", async () => {
    vi.mocked(getOperationsOverview).mockResolvedValue({
      scheduler: null,
      dependencies: [],
      failed_work: [],
      pending_jobs: 1,
    });
    vi.mocked(listScheduledJobs).mockResolvedValue([{
      id: "job-1",
      job_kind: "feed.refresh",
      dedupe_key: "feed-1",
      due_at: "2026-07-23T00:00:00Z",
      lease_owner: null,
      last_error_code: null,
    } as never]);
    vi.mocked(listJobRuns).mockResolvedValue([]);
    vi.mocked(listAuditEvents).mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <OperationsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("已安排任务")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行到期任务" })).toHaveAttribute("title", "执行所有已经到期的抓取、选择、通知和下载任务");
    const summary = screen.getByText("作业、运行记录和原始审计标识").closest("summary");
    const diagnostics = summary?.closest("details");
    expect(diagnostics).not.toHaveAttribute("open");
    fireEvent.click(summary as HTMLElement);
    expect(diagnostics).toHaveAttribute("open");
    expect(screen.getByRole("heading", { name: "后台任务" })).toBeInTheDocument();
    expect(screen.getByText("计划执行时间和当前状态")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "运行记录" })).toBeInTheDocument();
    expect(screen.getByText("记录每次后台任务的运行结果")).toBeInTheDocument();
    expect(screen.queryByText(/持久化|租约/)).not.toBeInTheDocument();
  });
});
