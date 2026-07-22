import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

    expect(screen.getByRole("heading", { name: "RSS 动画" })).toBeInTheDocument();
    expect(screen.getByText("先把一个或多个 RSS 动画匹配到 Bangumi 动画，再单独选择是否追番。“未匹配到动画”表示尚未对应上 Bangumi 动画 ID。")).toBeInTheDocument();
    expect(screen.getByText("New Anime")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开《New Anime》的 RSS 标题" }));
    expect(screen.getByRole("link", { name: "查看识别结果" })).toHaveAttribute(
      "href",
      "/candidates?series=anime%3Aanime-1",
    );
    fireEvent.click(screen.getByRole("button", { name: "RSS 动画" }));
    expect(screen.queryByText("New Anime")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "RSS 动画" }));
    expect(screen.getByRole("button", { name: "收起《New Anime》的 RSS 标题" })).toBeInTheDocument();
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

  it("matches an unmatched RSS title without starting to follow it", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "匹配" }));
    expect(screen.getByText("1 集 · 1 个候选 · 1 个 RSS 标题 · 未匹配到动画")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "匹配 Bangumi 动画" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "本地创建" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "搜索 Bangumi 动画" })).toHaveValue("New Anime");
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(await within(dialog).findByRole("button", { name: "匹配" }));

    await waitFor(() => expect(bindCatalogTitles).toHaveBeenCalledWith(
      "anime-123",
      ["New Anime", "新番 第二季"],
    ));
    expect(createSubscription).not.toHaveBeenCalled();
    expect(await screen.findByText("已将 1 个 RSS 动画匹配到《新番》。")).toBeInTheDocument();
  });

  it("matches multiple RSS titles to one anime and then groups them into one row", async () => {
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
    const matchedAnime = { id: "anime-123", primary_title: "新番", bangumi_id: 123 } as never;
    vi.mocked(importBangumi).mockResolvedValue(matchedAnime);
    const firstGroup = {
      key: "title:new-anime:1",
      series_title: "New Anime RSS",
      series_key: "new-anime",
      series_identity: "title:new-anime",
      anime_id: null,
      catalog_match_status: "unmatched",
      season: 1,
      episode_key: "1",
      candidate_count: 1,
      candidates: [{ series_title: "New Anime RSS", title_variants: ["New Anime", "新番"] } as never],
      latest_seen_at: "2026-07-22T00:00:00Z",
    };
    const secondGroup = {
      key: "title:shinban:2",
      series_title: "新番动画 RSS",
      series_key: "shinban",
      series_identity: "title:shinban",
      anime_id: null,
      catalog_match_status: "unmatched",
      season: 1,
      episode_key: "2",
      candidate_count: 1,
      candidates: [{ series_title: "新番动画 RSS", title_variants: ["Shinban 2026"] } as never],
      latest_seen_at: "2026-07-22T00:01:00Z",
    };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiscoveredSeriesSection anime={[]} subscriptions={[]} groups={[firstGroup, secondGroup]} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const section = within(view.container);

    fireEvent.click(section.getByRole("checkbox", { name: "选择 RSS 动画 New Anime RSS" }));
    fireEvent.click(section.getByRole("checkbox", { name: "选择 RSS 动画 新番动画 RSS" }));
    fireEvent.click(section.getByRole("button", { name: "匹配所选（2）" }));
    expect(section.getByText("将 “New Anime RSS”、“新番动画 RSS” 固定到同一部 Bangumi 动画；匹配后不会自动开始追番。")).toBeInTheDocument();
    fireEvent.click(section.getByRole("button", { name: "搜索" }));
    fireEvent.click(await within(section.getByRole("dialog")).findByRole("button", { name: "匹配" }));

    await waitFor(() => expect(bindCatalogTitles).toHaveBeenCalledTimes(2));
    expect(bindCatalogTitles).toHaveBeenNthCalledWith(1, "anime-123", ["New Anime", "新番"]);
    expect(bindCatalogTitles).toHaveBeenNthCalledWith(2, "anime-123", ["Shinban 2026"]);
    expect(createSubscription).not.toHaveBeenCalled();

    view.rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiscoveredSeriesSection
            anime={[matchedAnime]}
            subscriptions={[]}
            groups={[
              { ...firstGroup, key: "anime:anime-123:1", series_identity: "anime:anime-123", anime_id: "anime-123", catalog_match_status: "matched" },
              { ...secondGroup, key: "anime:anime-123:2", series_identity: "anime:anime-123", anime_id: "anime-123", catalog_match_status: "matched" },
            ]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(section.getByRole("button", { name: "开始追番" })).toBeInTheDocument();
    expect(section.queryByRole("button", { name: "匹配" })).not.toBeInTheDocument();
    fireEvent.click(section.getByRole("button", { name: "展开《新番》的 RSS 标题" }));
    expect(section.getByText("New Anime RSS")).toBeInTheDocument();
    expect(section.getByText("新番动画 RSS")).toBeInTheDocument();
    expect(section.getByText("以下标题均对应《新番》")).toBeInTheDocument();
  });
});
