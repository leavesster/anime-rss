import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadsPage } from "../src/features/downloads/DownloadsPage";
import { ReleasesPage } from "../src/features/releases/ReleasesPage";
import { getDownloadConfig, listDownloadTasks, listReleases } from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  getDownloadConfig: vi.fn(),
  listDownloadTasks: vi.fn(),
  listReleases: vi.fn(),
  processDownloads: vi.fn(),
  retryDownloadTask: vi.fn(),
  saveDownloadConfig: vi.fn(),
  submitReleaseDownload: vi.fn(),
  testDownloadConnection: vi.fn(),
}));

afterEach(cleanup);

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function task(id: string, state: string) {
  return {
    id,
    display_name: `${id} task`,
    info_hash: `${id}`.padEnd(40, "0"),
    state,
    progress: state === "completed" ? 1 : 0.4,
    requested_save_path: null,
    actual_save_path: null,
    category: null,
    tags: [],
    stale: false,
    error_code: state === "failed" ? "add_rejected" : null,
    last_observed_at: "2026-07-23T00:00:00Z",
  } as never;
}

describe("large list controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getDownloadConfig).mockResolvedValue(null);
  });

  it("puts failed downloads first and filters the action queue", async () => {
    vi.mocked(listDownloadTasks).mockResolvedValue([
      task("completed", "completed"),
      task("active", "submitted"),
      task("failed", "failed"),
    ]);
    const view = render(<QueryClientProvider client={client()}><DownloadsPage /></QueryClientProvider>);

    expect(await screen.findByText("failed task")).toBeInTheDocument();
    expect([...view.container.querySelectorAll(".download-row")].map((row) => row.textContent)).toEqual([
      expect.stringContaining("failed task"),
      expect.stringContaining("active task"),
      expect.stringContaining("completed task"),
    ]);

    fireEvent.click(screen.getByRole("tab", { name: /需处理/ }));
    expect(screen.getByText("failed task")).toBeInTheDocument();
    expect(screen.queryByText("active task")).not.toBeInTheDocument();
    expect(screen.queryByText("completed task")).not.toBeInTheDocument();
  });

  it("reveals releases in bounded batches", async () => {
    vi.mocked(listDownloadTasks).mockResolvedValue([]);
    vi.mocked(listReleases).mockResolvedValue(Array.from({ length: 41 }, (_, index) => ({
      id: `release-${index + 1}`,
      display_name: `Release ${index + 1}`,
      identity_kind: "btih",
      identity_value: `${index + 1}`.padEnd(40, "0"),
      btih: `${index + 1}`.padEnd(40, "0"),
      btmh: null,
      automation_eligible: true,
      first_seen_at: "2026-07-23T00:00:00Z",
      source_count: 1,
    } as never)));

    render(<QueryClientProvider client={client()}><MemoryRouter><ReleasesPage /></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText("Release 1")).toBeInTheDocument();
    expect(screen.getByText("显示 40 / 41")).toBeInTheDocument();
    expect(screen.queryByText("Release 41")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "再显示 1 条" }));
    expect(screen.getByText("Release 41")).toBeInTheDocument();
    expect(screen.getByText("显示 41 / 41")).toBeInTheDocument();
  });
});
