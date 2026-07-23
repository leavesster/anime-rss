import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { DashboardPage } from "../src/features/dashboard/DashboardPage";
import {
  getOperationsOverview,
  getScheduleOverview,
  getSeasonalOverview,
  listFeeds,
  listReleases,
  listRssMatches,
  refreshSchedule,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  getOperationsOverview: vi.fn(),
  getScheduleOverview: vi.fn(),
  getSeasonalOverview: vi.fn(),
  dismissSeasonalAnime: vi.fn(),
  followSeasonalAnime: vi.fn(),
  markSeasonalAnimeWatched: vi.fn(),
  listFeeds: vi.fn(),
  listReleases: vi.fn(),
  listRssMatches: vi.fn(),
  refreshSchedule: vi.fn(),
  refreshSeasonalOverview: vi.fn(),
}));

const schedule = {
  calendar: [{ date: "2026-07-23", episodes: [] }],
  missing: [],
};

describe("dashboard schedule", () => {
  it("loads the calendar without synchronizing and syncs only after explicit action", async () => {
    vi.mocked(listFeeds).mockResolvedValue([]);
    vi.mocked(listReleases).mockResolvedValue([]);
    vi.mocked(listRssMatches).mockResolvedValue([]);
    vi.mocked(getOperationsOverview).mockResolvedValue({
      scheduler: null,
      dependencies: [],
      failed_work: [],
      pending_jobs: 0,
    });
    vi.mocked(getScheduleOverview).mockResolvedValue(schedule);
    vi.mocked(getSeasonalOverview).mockResolvedValue({
      year: 2026,
      quarter: 3,
      title: "2026 年 7 月新番",
      fetched_at: "2026-07-23T00:00:00Z",
      stale: false,
      items: [],
    });
    vi.mocked(refreshSchedule).mockResolvedValue(schedule);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "播出日历" })).toBeInTheDocument();
    expect(getScheduleOverview).toHaveBeenCalledTimes(1);
    expect(refreshSchedule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "同步播出信息" }));

    await waitFor(() => expect(refreshSchedule).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("status")).toHaveTextContent("播出信息已同步");
  });
});
