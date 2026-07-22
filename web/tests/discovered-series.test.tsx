import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { DiscoveredSeriesSection } from "../src/features/subscriptions/DiscoveredSeriesSection";
import { createLocalAnime, createSubscription } from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  createLocalAnime: vi.fn(),
  createSubscription: vi.fn(),
}));

describe("RSS discovered series", () => {
  it("shows an untracked recognized series and starts following it", async () => {
    vi.mocked(createLocalAnime).mockResolvedValue({ id: "anime-1" } as never);
    vi.mocked(createSubscription).mockResolvedValue({ id: "subscription-1" } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DiscoveredSeriesSection
            anime={[]}
            subscriptions={[]}
            groups={[{
              key: "newanime:1",
              series_title: "New Anime",
              series_key: "newanime",
              season: 1,
              episode_key: "1",
              candidate_count: 2,
              candidates: [],
              latest_seen_at: "2026-07-22T00:00:00Z",
            }]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("New Anime")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看 New Anime 的识别结果" })).toHaveAttribute(
      "href",
      "/candidates?series=newanime",
    );
    fireEvent.click(screen.getByRole("button", { name: "开始追番" }));

    await waitFor(() => expect(createSubscription).toHaveBeenCalled());
    expect(createLocalAnime).toHaveBeenCalledWith("New Anime", []);
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
            subscriptions={[{ match_keys: ["newanime"] } as never]}
            groups={[{
              key: "newanime:1",
              series_title: "New Anime",
              series_key: "newanime",
              season: 1,
              episode_key: "1",
              candidate_count: 1,
              candidates: [],
              latest_seen_at: "2026-07-22T00:00:00Z",
            }]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
