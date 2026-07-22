import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DownloadsPage } from "../src/features/downloads/DownloadsPage";
import { getDownloadConfig, listDownloadTasks } from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  getDownloadConfig: vi.fn(),
  listDownloadTasks: vi.fn(),
  processDownloads: vi.fn(),
  retryDownloadTask: vi.fn(),
  saveDownloadConfig: vi.fn(),
  testDownloadConnection: vi.fn(),
}));

describe("download task names", () => {
  it("shows the release name before its hash", async () => {
    vi.mocked(getDownloadConfig).mockResolvedValue(null);
    vi.mocked(listDownloadTasks).mockResolvedValue([{
      id: "task-1",
      display_name: "[Group] Readable Anime - 01.mkv",
      info_hash: "0123456789abcdef0123456789abcdef01234567",
      state: "downloading",
      progress: 0.5,
      tags: [],
      stale: false,
    } as never]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <DownloadsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("[Group] Readable Anime - 01.mkv")).toBeInTheDocument();
    expect(screen.getByText(/0123456789/)).toBeInTheDocument();
  });
});
