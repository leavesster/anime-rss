import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScheduleDialog } from "../src/features/subscriptions/ScheduleDialog";
import {
  deleteEpisodeScheduleOverride,
  listAnimeEpisodeHistory,
  listEpisodeScheduleOverrides,
  saveEpisodeScheduleOverride,
  syncSchedule,
  type Anime,
  updateAnimeSchedule,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  deleteEpisodeScheduleOverride: vi.fn(),
  listAnimeEpisodeHistory: vi.fn(),
  listEpisodeScheduleOverrides: vi.fn(),
  saveEpisodeScheduleOverride: vi.fn(),
  syncSchedule: vi.fn(),
  updateAnimeSchedule: vi.fn(),
}));

const anime = {
  id: "anime-1",
  bangumi_id: null,
  primary_title: "Irregular Anime",
  title_zh: "Irregular Anime",
  title_ja: null,
  title_en: null,
  summary: null,
  air_date: "2026-07-20",
  episode_count: 12,
  airing_weekday: 0,
  airing_time: "01:00",
  schedule_timezone: "UTC",
  schedule_source: "manual",
  schedule_updated_at: "2026-07-20T00:00:00Z",
  cover_url: null,
  source: "local",
  version: 1,
  titles: [],
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
} satisfies Anime;

describe("episode schedule overrides", () => {
  it("creates and deletes an override while refreshing the projection", async () => {
    vi.mocked(listAnimeEpisodeHistory).mockResolvedValue([]);
    vi.mocked(listEpisodeScheduleOverrides).mockResolvedValue([{
      id: "override-2",
      anime_id: anime.id,
      episode_key: "2",
      expected_at: "2026-07-27T01:00:00Z",
      cancelled: false,
      source: "manual",
      note: "double episode",
      version: 3,
      created_at: "2026-07-20T00:00:00Z",
      updated_at: "2026-07-20T00:00:00Z",
    }]);
    vi.mocked(saveEpisodeScheduleOverride).mockResolvedValue({
      id: "override-sp1",
      anime_id: anime.id,
      episode_key: "SP1",
      expected_at: "2026-07-23T03:00:00Z",
      cancelled: false,
      source: "manual",
      note: "special",
      version: 1,
      created_at: "2026-07-20T00:00:00Z",
      updated_at: "2026-07-20T00:00:00Z",
    });
    vi.mocked(deleteEpisodeScheduleOverride).mockResolvedValue();
    vi.mocked(syncSchedule).mockResolvedValue({
      generated: 2,
      acquired: 0,
      missing: 0,
      notifications: 0,
    });
    vi.mocked(updateAnimeSchedule).mockResolvedValue(anime);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ScheduleDialog anime={anime} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("集数标识"), { target: { value: "SP1" } });
    fireEvent.change(screen.getByLabelText("预计播出时间"), {
      target: { value: "2026-07-23T03:00" },
    });
    fireEvent.change(screen.getByLabelText("备注"), { target: { value: "special" } });
    fireEvent.click(screen.getByRole("button", { name: "保存逐集调整" }));

    await waitFor(() => expect(saveEpisodeScheduleOverride).toHaveBeenCalled());
    expect(vi.mocked(saveEpisodeScheduleOverride).mock.calls[0]?.[0]).toBe(anime.id);
    expect(vi.mocked(saveEpisodeScheduleOverride).mock.calls[0]?.[1]).toBe("SP1");
    expect(vi.mocked(saveEpisodeScheduleOverride).mock.calls[0]?.[2]).toMatchObject({
      cancelled: false,
      note: "special",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("逐集调整已保存并刷新日历");

    fireEvent.click(await screen.findByRole("button", { name: "删除第 2 集调整" }));
    await waitFor(() => {
      expect(deleteEpisodeScheduleOverride).toHaveBeenCalledWith(anime.id, "2", 3);
    });
    expect(syncSchedule).toHaveBeenCalledTimes(2);
  });
});
