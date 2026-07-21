import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SetupWizard } from "../src/features/setup/SetupWizard";
import {
  listSubscriptions,
  markSetupStep,
  previewBackfill,
} from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  listSubscriptions: vi.fn(),
  markSetupStep: vi.fn(),
  previewBackfill: vi.fn(),
}));

describe("guided setup", () => {
  it("finishes from the read-only candidate preview without committing backfill", async () => {
    vi.mocked(listSubscriptions).mockResolvedValue([{
      id: "subscription-1",
      anime_id: "anime-1",
      anime_title: "Test Anime",
      state: "active",
      match_keys: ["test anime"],
      rules: { fallback_wait_minutes: 120 },
      uses_global_rules: true,
      activation_at: "2026-07-22T00:00:00Z",
      save_path: null,
      version: 1,
      created_at: "2026-07-22T00:00:00Z",
      updated_at: "2026-07-22T00:00:00Z",
    }]);
    vi.mocked(previewBackfill).mockResolvedValue([]);
    vi.mocked(markSetupStep).mockResolvedValue({
      timezone: "Asia/Shanghai",
      interface_language: "zh-CN",
      missing_episode_grace_hours: 24,
      setup_completed_steps: [],
      setup_completed: true,
      version: 8,
      updated_at: "2026-07-22T00:00:00Z",
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SetupWizard settings={{
          timezone: "Asia/Shanghai",
          interface_language: "zh-CN",
          missing_episode_grace_hours: 24,
          setup_completed_steps: [
            "administrator", "instance_preferences", "qbittorrent_connection",
            "download_defaults", "feed", "global_preferences", "subscription",
          ],
          setup_completed: false,
          version: 7,
          updated_at: "2026-07-22T00:00:00Z",
        }} />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "生成候选预览" }));
    expect(await screen.findByText(/当前没有已知候选/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "完成初始化" }));
    await waitFor(() => expect(markSetupStep).toHaveBeenCalledWith("candidate_preview"));
    expect(previewBackfill).toHaveBeenCalledWith("subscription-1");
  });
});
