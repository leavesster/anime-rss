import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubscriptionsPage } from "../src/features/subscriptions/SubscriptionsPage";
import {
  getGlobalPreferences,
  listAnime,
  listDecisions,
  listEpisodeGroups,
  listSelectionSlots,
  listSubscriptions,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  createSubscription: vi.fn(),
  getGlobalPreferences: vi.fn(),
  listAnime: vi.fn(),
  listDecisions: vi.fn(),
  listEpisodeGroups: vi.fn(),
  listSelectionSlots: vi.fn(),
  listSubscriptions: vi.fn(),
  saveGlobalPreferences: vi.fn(),
  updateSubscription: vi.fn(),
}));

afterEach(cleanup);

describe("subscription page accessibility", () => {
  const writeText = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    vi.mocked(listAnime).mockResolvedValue([{
      id: "anime-1",
      bangumi_id: 54321,
      primary_title: "可以复制的新番",
    } as never]);
    vi.mocked(listSubscriptions).mockResolvedValue([{
      id: "subscription-1",
      anime_id: "anime-1",
      anime_title: "可以复制的新番",
      state: "following",
      match_keys: ["可以复制的新番"],
      rules: {},
      uses_global_rules: true,
      activation_at: "2026-07-22T00:00:00Z",
      version: 1,
    } as never]);
    vi.mocked(listSelectionSlots).mockResolvedValue([]);
    vi.mocked(listDecisions).mockResolvedValue([]);
    vi.mocked(listEpisodeGroups).mockResolvedValue([]);
    vi.mocked(getGlobalPreferences).mockResolvedValue({
      id: "global",
      name: "全局默认",
      rules: {},
      version: 1,
      updated_at: null,
    } as never);
  });

  it("copies a title and exposes its Bangumi destination", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SubscriptionsPage />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "复制《可以复制的新番》名称" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("可以复制的新番"));
    expect(screen.getByRole("button", { name: "已复制《可以复制的新番》名称" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "在 Bangumi 查看《可以复制的新番》" })).toHaveAttribute(
      "href",
      "https://bgm.tv/subject/54321",
    );
  });

  it("toggles recent decisions from the full heading text area", async () => {
    vi.mocked(listDecisions).mockResolvedValue([{
      id: "decision-1",
      kind: "selected_preferred",
      anime_title: "可以折叠的新番",
      episode_key: "01",
      candidate_snapshot: {
        release_group: "字幕组",
        resolution: "1080p",
      },
      created_at: "2026-07-23T00:00:00Z",
    } as never]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SubscriptionsPage />
      </QueryClientProvider>,
    );

    const toggle = await screen.findByRole("button", { name: /最近选择.*保留每次选择的原因/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("可以折叠的新番 · 第 01 集")).toBeInTheDocument();

    fireEvent.click(screen.getByText("保留每次选择的原因，以及当时的字幕组、画质和编码。"));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("可以折叠的新番 · 第 01 集")).not.toBeInTheDocument();
  });
});
