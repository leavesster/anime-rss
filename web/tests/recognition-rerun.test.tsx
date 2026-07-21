import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CandidatesPage } from "../src/features/recognition/CandidatesPage";
import {
  listEpisodeGroups,
  listUnmatchedReleases,
  rerunRecognition,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  confirmCandidate: vi.fn(),
  listEpisodeGroups: vi.fn(),
  listUnmatchedReleases: vi.fn(),
  remapRelease: vi.fn(),
  rerunRecognition: vi.fn(),
}));

describe("recognition parser rerun", () => {
  it("runs a release again and reports that unchanged evidence was appended", async () => {
    vi.mocked(listEpisodeGroups).mockResolvedValue([{
      key: "parseranime:1",
      series_title: "Parser Anime",
      series_key: "parseranime",
      season: 1,
      episode_key: "1",
      candidate_count: 1,
      latest_seen_at: "2026-07-22T00:00:00Z",
      candidates: [{
        id: "candidate-1",
        release_id: "release-1",
        source_title: "[Group] Parser Anime - 01 [1080p]",
        series_title: "Parser Anime",
        series_key: "parseranime",
        season: 1,
        episode_start: "1",
        episode_end: null,
        episode_key: "1",
        release_group: "Group",
        resolution: "1080p",
        video_codec: null,
        subtitle_language: null,
        revision: 1,
        content_kind: "episode",
        confidence: "high",
        recognition_eligible: true,
        first_seen_at: "2026-07-22T00:00:00Z",
        supersedes_candidate_id: null,
        superseded_by_candidate_id: null,
        superseded_at: null,
      }],
    }]);
    vi.mocked(listUnmatchedReleases).mockResolvedValue([]);
    vi.mocked(rerunRecognition).mockResolvedValue({
      attempt_id: "attempt-2",
      release_id: "release-1",
      parser_version: "title-rules.v1",
      parsed_at: "2026-07-22T00:01:00Z",
      confidence: "high",
      reason_code: "parsed_group_series_episode",
      candidate_id: "candidate-1",
      previous_candidate_id: "candidate-1",
      candidate_changed: false,
      candidate_adopted: false,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <CandidatesPage />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "重新解析" }));

    await waitFor(() => expect(rerunRecognition).toHaveBeenCalled());
    expect(vi.mocked(rerunRecognition).mock.calls[0]?.[0]).toBe("release-1");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "解析结果未变化，已追加 title-rules.v1 的运行证据。",
    );
  });
});
