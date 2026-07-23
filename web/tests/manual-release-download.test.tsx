import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReleasesPage } from "../src/features/releases/ReleasesPage";
import {
  getDownloadConfig,
  listDownloadTasks,
  listReleases,
  submitReleaseDownload,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  getDownloadConfig: vi.fn(),
  listDownloadTasks: vi.fn(),
  listReleases: vi.fn(),
  submitReleaseDownload: vi.fn(),
}));

const release = {
  id: "release-1",
  display_name: "[Group] Anime - 01.mkv",
  identity_kind: "btih",
  identity_value: "0123456789abcdef0123456789abcdef01234567",
  btih: "0123456789abcdef0123456789abcdef01234567",
  btmh: null,
  automation_eligible: true,
  first_seen_at: "2026-07-22T00:00:00Z",
  source_count: 1,
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReleasesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("manual release download", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listReleases).mockResolvedValue([release]);
    vi.mocked(listDownloadTasks).mockResolvedValue([]);
  });

  it("queues a BTIH release and reports the durable background action", async () => {
    vi.mocked(getDownloadConfig).mockResolvedValue({
      adapter: "qbittorrent",
      base_url_redacted: "http://qbittorrent.local",
      username: "admin",
      default_save_path: null,
      default_category: null,
      default_tags: [],
      password_configured: true,
      version: 1,
      last_tested_at: null,
      last_success_at: null,
      last_error_code: null,
    });
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
    renderPage();

    expect(await screen.findByText("[Group] Anime - 01.mkv")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "种子列表" })).toBeInTheDocument();
    expect(screen.getByText("去重后列表")).toBeInTheDocument();
    expect(screen.getByText("种子名称 / 种子哈希")).toBeInTheDocument();
    expect(screen.getByText("BT 标识")).toBeInTheDocument();
    expect(screen.getByText("是否可靠")).toBeInTheDocument();
    expect(screen.getByText("BTIH")).toBeInTheDocument();
    expect(screen.getByText("可靠")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "提交下载" }));

    await waitFor(() => expect(submitReleaseDownload).toHaveBeenCalled());
    expect(vi.mocked(submitReleaseDownload).mock.calls[0]?.[0]).toBe("release-1");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "下载任务已加入队列；调度器会在后台提交到 qBittorrent。",
    );
  });

  it("blocks submission and links to configuration when qBittorrent is not configured", async () => {
    vi.mocked(getDownloadConfig).mockResolvedValue(null);

    renderPage();

    expect(await screen.findByText("提交种子前需要先配置 qBittorrent。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "配置下载器" })).toHaveAttribute("href", "/downloads");
    expect(screen.getByRole("button", { name: "先配置下载器" })).toBeDisabled();
    expect(submitReleaseDownload).not.toHaveBeenCalled();
  });
});
