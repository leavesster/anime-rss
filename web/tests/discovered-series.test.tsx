import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { DiscoveredSeriesSection } from "../src/features/subscriptions/DiscoveredSeriesSection";
import {
  bindCatalogTitles,
  createSubscription,
  importBangumi,
  searchBangumi,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  bindCatalogTitles: vi.fn(),
  createLocalAnime: vi.fn(),
  createSubscription: vi.fn(),
  importBangumi: vi.fn(),
  searchBangumi: vi.fn(),
}));

describe("RSS discovered series", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bindCatalogTitles).mockResolvedValue({ id: "anime-123" } as never);
  });

  it("shows an untracked recognized series and starts following it", async () => {
    vi.mocked(createSubscription).mockResolvedValue({ id: "subscription-1" } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiscoveredSeriesSection
            anime={[{ id: "anime-1", primary_title: "New Anime" } as never]}
            subscriptions={[]}
            groups={[{
              key: "newanime:1",
              series_title: "New Anime",
              series_key: "newanime",
              series_identity: "anime:anime-1",
              anime_id: "anime-1",
              catalog_match_status: "matched",
              season: 1,
              episode_key: "1",
              candidate_count: 2,
              candidates: [{ title_variants: ["New Anime"] } as never],
              latest_seen_at: "2026-07-22T00:00:00Z",
            }]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("New Anime")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看 New Anime 的识别结果" })).toHaveAttribute(
      "href",
      "/candidates?series=anime%3Aanime-1",
    );
    fireEvent.click(screen.getByRole("button", { name: "开始追番" }));

    await waitFor(() => expect(createSubscription).toHaveBeenCalled());
    expect(createSubscription).toHaveBeenCalledWith(expect.objectContaining({
      anime_id: "anime-1",
      use_global_rules: true,
    }));
  });

  it("does not show a series already covered by a subscription", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiscoveredSeriesSection
            anime={[]}
            subscriptions={[{ anime_id: "anime-1", match_keys: ["newanime"] } as never]}
            groups={[{
              key: "newanime:1",
              series_title: "New Anime",
              series_key: "newanime",
              series_identity: "anime:anime-1",
              anime_id: "anime-1",
              catalog_match_status: "matched",
              season: 1,
              episode_key: "1",
              candidate_count: 1,
              candidates: [{ title_variants: ["New Anime"] } as never],
              latest_seen_at: "2026-07-22T00:00:00Z",
            }]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("binds an unmatched RSS title through Bangumi before following", async () => {
    vi.mocked(searchBangumi).mockResolvedValue({
      stale: false,
      items: [{
        bangumi_id: 123,
        name: "New Anime",
        name_cn: "新番",
        summary: null,
        air_date: "2026-07-01",
        episode_count: 12,
        cover_url: null,
        aliases: [],
      }],
    });
    vi.mocked(importBangumi).mockResolvedValue({ id: "anime-123", primary_title: "新番" } as never);
    vi.mocked(createSubscription).mockResolvedValue({ id: "subscription-123" } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiscoveredSeriesSection
            anime={[]}
            subscriptions={[]}
            groups={[{
              key: "title:newanime:1",
              series_title: "New Anime",
              series_key: "newanime",
              series_identity: "title:newanime",
              anime_id: null,
              catalog_match_status: "unmatched",
              season: 1,
              episode_key: "1",
              candidate_count: 1,
              candidates: [{ title_variants: ["New Anime", "新番 第二季"] } as never],
              latest_seen_at: "2026-07-22T00:00:00Z",
            }]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "匹配并追番" }));
    expect(screen.getByRole("textbox", { name: "搜索 Bangumi 动画" })).toHaveValue("New Anime");
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    fireEvent.click(await screen.findByRole("button", { name: "导入" }));

    await waitFor(() => expect(bindCatalogTitles).toHaveBeenCalledWith(
      "anime-123",
      ["New Anime", "新番 第二季"],
    ));
    expect(vi.mocked(bindCatalogTitles).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(createSubscription).mock.invocationCallOrder[0],
    );
    expect(createSubscription).toHaveBeenCalledWith(expect.objectContaining({
      anime_id: "anime-123",
      aliases: [],
    }));
    expect(await screen.findByText("已合并到《新番》并开始追番。")).toBeInTheDocument();
  });
});
