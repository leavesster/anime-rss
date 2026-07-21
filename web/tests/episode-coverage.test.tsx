import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EpisodeControlDialog } from "../src/features/subscriptions/EpisodeControlDialog";
import {
  listDecisions,
  listManualActions,
  listSelectionSlots,
  previewBackfill,
  type Subscription,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  listDecisions: vi.fn(),
  listManualActions: vi.fn(),
  listSelectionSlots: vi.fn(),
  markEpisodeAcquired: vi.fn(),
  previewBackfill: vi.fn(),
  rejectCandidate: vi.fn(),
  resetEpisode: vi.fn(),
  selectCandidate: vi.fn(),
}));

const subscription = {
  id: "subscription-1",
  anime_id: "anime-1",
  anime_title: "Overlap Anime",
} as Subscription;

describe("episode range coverage", () => {
  it("explains a partial overlap and keeps the explicit manual command", async () => {
    vi.mocked(previewBackfill).mockResolvedValue([{
      episode_key: "1-2",
      selected_candidate_id: null,
      candidates: [{
        candidate_id: "candidate-range",
        source_title: "[Group] Overlap Anime - 01-02",
        release_group: "Group",
        eligible: false,
        preferred: true,
        rank: [0, 0, 0, 0, -1, "2026-07-22T00:00:00Z", "release"],
        first_loss_field: null,
        rejection_reasons: ["partially_overlaps_acquired_episodes"],
        coverage_status: "partial",
        covered_episode_keys: ["1", "2"],
        already_covered_episode_keys: ["1"],
      }],
    }]);
    vi.mocked(listSelectionSlots).mockResolvedValue([{
      id: "slot-range",
      subscription_id: subscription.id,
      anime_title: subscription.anime_title,
      episode_key: "1-2",
      state: "needs_confirmation",
      fallback_deadline: null,
      best_candidate_id: "candidate-range",
      selected_decision_id: null,
      confirmation_reason: {
        kind: "episode_coverage_overlap",
        covered_episode_keys: ["1", "2"],
        already_covered_episode_keys: ["1"],
      },
      version: 1,
      updated_at: "2026-07-22T00:00:00Z",
    }]);
    vi.mocked(listDecisions).mockResolvedValue([]);
    vi.mocked(listManualActions).mockResolvedValue([]);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EpisodeControlDialog subscription={subscription} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/其中第 1 集已获取/)).toBeInTheDocument();
    expect(screen.getByText(/覆盖第 1、2 集；第 1 集已获取/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认重复并选择" })).toBeEnabled();
  });
});
