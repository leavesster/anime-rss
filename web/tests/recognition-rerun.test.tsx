import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { CandidatesPage } from "../src/features/recognition/CandidatesPage";
import {
  dismissRelease,
  listAnime,
  listEpisodeGroups,
  listUnmatchedReleases,
  rerunRecognition,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  confirmCandidate: vi.fn(),
  dismissRelease: vi.fn(),
  listAnime: vi.fn(),
  listEpisodeGroups: vi.fn(),
  listUnmatchedReleases: vi.fn(),
  remapRelease: vi.fn(),
  rerunRecognition: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(listAnime).mockResolvedValue([]);
});

describe("recognition parser rerun", () => {
  it("runs a release again and reports that unchanged evidence was appended", async () => {
    vi.mocked(listEpisodeGroups).mockResolvedValue([{
      key: "parseranime:1",
      series_title: "Parser Anime",
      series_key: "parseranime",
      series_identity: "title:parseranime",
      anime_id: null,
      catalog_match_status: "unmatched",
      season: 1,
      episode_key: "1",
      candidate_count: 1,
      latest_seen_at: "2026-07-22T00:00:00Z",
      candidates: [{
        id: "candidate-1",
        release_id: "release-1",
        source_title: "[Group] Parser Anime - 01 [1080p]",
        series_title: "Parser Anime",
        title_variants: ["Parser Anime"],
        series_key: "parseranime",
        anime_id: null,
        catalog_match_status: "unmatched",
        catalog_match_method: null,
        catalog_match_key: "parseranime",
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
        <MemoryRouter><CandidatesPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "重新解析" }));

    await waitFor(() => expect(rerunRecognition).toHaveBeenCalled());
    expect(vi.mocked(rerunRecognition).mock.calls[0]?.[0]).toBe("release-1");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "解析结果未变化，已追加 title-rules.v1 的运行证据。",
    );
  });

  it("dismisses an unmatched release after explicit confirmation", async () => {
    vi.mocked(listEpisodeGroups).mockResolvedValue([]);
    vi.mocked(listUnmatchedReleases).mockResolvedValue([{
      id: "attempt-1",
      release_id: "release-unmatched",
      source_title: "Unrecognized weekly package",
      confidence: "low",
      reason_code: "episode_not_found",
      parsed_at: "2026-07-22T00:00:00Z",
    }]);
    vi.mocked(dismissRelease).mockResolvedValue();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter><CandidatesPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("tab", { name: /待识别/ }));
    fireEvent.click(screen.getByRole("button", { name: "忽略" }));
    fireEvent.click(screen.getByRole("button", { name: "确认忽略" }));

    await waitFor(() => expect(dismissRelease).toHaveBeenCalled());
    expect(vi.mocked(dismissRelease).mock.calls[0]?.[0]).toBe("release-unmatched");
  });

  it("filters grouped candidates from a discovered-series deep link", async () => {
    const candidate = {
      id: "candidate-1",
      release_id: "release-1",
      source_title: "[Group] New Anime - 01 [1080p]",
      series_title: "New Anime",
      title_variants: ["New Anime"],
      series_key: "newanime",
      anime_id: null,
      catalog_match_status: "unmatched",
      catalog_match_method: null,
      catalog_match_key: "newanime",
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
    };
    vi.mocked(listEpisodeGroups).mockResolvedValue([
      { key: "title:newanime:1", series_title: "New Anime", series_key: "newanime", series_identity: "title:newanime", anime_id: null, catalog_match_status: "unmatched", season: 1, episode_key: "1", candidate_count: 1, candidates: [candidate], latest_seen_at: "2026-07-22T00:00:00Z" },
      { key: "title:otheranime:1", series_title: "Other Anime", series_key: "otheranime", series_identity: "title:otheranime", anime_id: null, catalog_match_status: "unmatched", season: 1, episode_key: "1", candidate_count: 1, candidates: [{ ...candidate, id: "candidate-2", series_title: "Other Anime", title_variants: ["Other Anime"], series_key: "otheranime", catalog_match_key: "otheranime" }], latest_seen_at: "2026-07-22T00:00:00Z" },
    ]);
    vi.mocked(listUnmatchedReleases).mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/candidates?series=title%3Anewanime"]}><CandidatesPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("正在查看", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New Anime" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Other Anime" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看全部动画" }));
    expect(await screen.findByRole("heading", { name: "Other Anime" })).toBeInTheDocument();
  });
});
