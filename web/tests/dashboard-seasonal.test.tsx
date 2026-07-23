import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SeasonalAnimeSection } from "../src/features/dashboard/SeasonalAnimeSection";
import {
  followSeasonalAnime,
  getSeasonalOverview,
  listRssMatches,
  markSeasonalAnimeWatched,
  refreshSeasonalOverview,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  dismissSeasonalAnime: vi.fn(),
  followSeasonalAnime: vi.fn(),
  getSeasonalOverview: vi.fn(),
  listRssMatches: vi.fn(),
  markSeasonalAnimeWatched: vi.fn(),
  refreshSeasonalOverview: vi.fn(),
}));

const items = [
  {
    bangumi_id: 101,
    name: "Follow Anime",
    name_cn: "准备追的新番",
    summary: "",
    air_date: "2026-07-04",
    episode_count: 12,
    cover_url: "https://lain.bgm.tv/101.jpg",
    platform: "TV",
    popularity: 100,
    rating_score: 8.2,
    rating_total: 321,
    status: "undecided",
    anime_id: "anime-101",
    subscription_id: null,
  },
  {
    bangumi_id: 102,
    name: "Dismissed Anime",
    name_cn: "已经不追的新番",
    summary: "",
    air_date: "2026-07-05",
    episode_count: 12,
    cover_url: null,
    platform: "WEB",
    popularity: 80,
    rating_score: null,
    rating_total: 0,
    status: "dismissed",
    anime_id: "anime-102",
    subscription_id: null,
  },
  {
    bangumi_id: 103,
    name: "Watched Anime",
    name_cn: "已经看完的新番",
    summary: "",
    air_date: "2026-07-06",
    episode_count: 12,
    cover_url: null,
    platform: "TV",
    popularity: 70,
    rating_score: 7.6,
    rating_total: 120,
    status: "watched",
    anime_id: null,
    subscription_id: null,
  },
] as const;

afterEach(cleanup);

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SeasonalAnimeSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("seasonal anime homepage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSeasonalOverview).mockResolvedValue({
      year: 2026,
      quarter: 3,
      title: "2026 年 7 月新番",
      fetched_at: "2026-07-23T00:00:00Z",
      stale: false,
      items: [...items],
    });
    vi.mocked(listRssMatches).mockResolvedValue([{
      anime_id: "anime-101",
      candidate_count: 2,
      episode_count: 1,
      latest_seen_at: "2026-07-23T00:00:00Z",
      conflicts: [],
    }]);
    vi.mocked(followSeasonalAnime).mockResolvedValue({
      bangumi_id: 101,
      status: "following",
      anime_id: "anime-101",
      subscription_id: "subscription-101",
    });
    vi.mocked(markSeasonalAnimeWatched).mockResolvedValue({
      bangumi_id: 101,
      status: "watched",
      anime_id: null,
      subscription_id: null,
    });
  });

  it("filters decisions and follows an undecided anime", async () => {
    renderSection();

    expect(await screen.findByRole("heading", { name: "2026 年 7 月新番" })).toBeInTheDocument();
    expect(screen.getByText("准备追的新番")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "《准备追的新番》封面" })).toHaveAttribute(
      "src",
      "https://lain.bgm.tv/101.jpg",
    );
    expect(screen.getByLabelText("Bangumi 321 人评分")).toHaveTextContent("8.2");
    const followedCard = screen.getByText("准备追的新番").closest("article");
    expect(within(followedCard!).getByText("RSS 已匹配")).toBeInTheDocument();
    expect(within(followedCard!).getByText("1 集 · 2 个种子")).toBeInTheDocument();
    const dismissedCard = screen.getByText("已经不追的新番").closest("article");
    expect(within(dismissedCard!).getByText("RSS 未匹配")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "不追 1" }));
    expect(screen.queryByText("准备追的新番")).not.toBeInTheDocument();
    expect(screen.getByText("已经不追的新番")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "已看完 1" }));
    expect(screen.getByText("已经看完的新番")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "待决定 1" }));
    const card = screen.getByText("准备追的新番").closest("article");
    fireEvent.click(within(card!).getByRole("button", { name: "追番" }));

    await waitFor(() => expect(followSeasonalAnime).toHaveBeenCalledWith(101));
  });

  it("marks an undecided anime as watched", async () => {
    renderSection();
    const card = (await screen.findByText("准备追的新番")).closest("article");

    fireEvent.click(within(card!).getByRole("button", { name: "已看完" }));

    await waitFor(() => expect(markSeasonalAnimeWatched).toHaveBeenCalledWith(101));
  });

  it("switches quarters and explicitly refreshes the selected period", async () => {
    vi.mocked(refreshSeasonalOverview).mockResolvedValue({
      year: 2026,
      quarter: 2,
      title: "2026 年 4 月新番",
      fetched_at: "2026-07-23T01:00:00Z",
      stale: false,
      items: [],
    });
    renderSection();
    await screen.findByRole("heading", { name: "2026 年 7 月新番" });

    fireEvent.click(screen.getByRole("button", { name: "上一季度" }));
    await waitFor(() => expect(getSeasonalOverview).toHaveBeenLastCalledWith(2026, 2));
    const refreshButton = screen.getByRole("button", { name: "刷新本季新番" });
    await waitFor(() => expect(refreshButton).toBeEnabled());
    fireEvent.click(refreshButton);

    await waitFor(() => expect(refreshSeasonalOverview).toHaveBeenCalledWith(2026, 2));
  });
});
