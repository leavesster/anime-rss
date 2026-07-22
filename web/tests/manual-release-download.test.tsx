import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReleasesPage } from "../src/features/releases/ReleasesPage";
import {
  listDownloadTasks,
  listReleases,
  submitReleaseDownload,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  listDownloadTasks: vi.fn(),
  listReleases: vi.fn(),
  submitReleaseDownload: vi.fn(),
}));

describe("manual release download", () => {
  it("queues a BTIH release and reports the durable background action", async () => {
    vi.mocked(listReleases).mockResolvedValue([{
      id: "release-1",
      display_name: "[Group] Anime - 01.mkv",
      identity_kind: "btih",
      identity_value: "0123456789abcdef0123456789abcdef01234567",
      btih: "0123456789abcdef0123456789abcdef01234567",
      btmh: null,
      automation_eligible: true,
      first_seen_at: "2026-07-22T00:00:00Z",
      source_count: 1,
    }]);
    vi.mocked(listDownloadTasks).mockResolvedValue([]);
    vi.mocked(submitReleaseDownload).mockResolvedValue({
      id: "task-1",
      origin_kind: "manual_release",
      decision_id: null,
      release_id: "release-1",
      subscription_id: null,
      info_hash: "0123456789abcdef0123456789abcdef01234567",
      state: "planned",
      requested_save_path: null,
      actual_save_path: null,
      category: null,
      tags: [],
      progress: 0,
      stale: false,
      missing_observation_count: 0,
      error_code: null,
      attempt_count: 0,
      next_retry_at: "2026-07-22T00:00:00Z",
      last_observed_at: null,
      supersedes_decision_id: null,
      superseded_by_decision_id: null,
      superseded_at: null,
      created_at: "2026-07-22T00:00:00Z",
      updated_at: "2026-07-22T00:00:00Z",
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ReleasesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("[Group] Anime - 01.mkv")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "提交下载" }));

    await waitFor(() => expect(submitReleaseDownload).toHaveBeenCalled());
    expect(vi.mocked(submitReleaseDownload).mock.calls[0]?.[0]).toBe("release-1");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "下载任务已加入队列；调度器会在后台提交到 qBittorrent。",
    );
  });
});
