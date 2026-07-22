import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FeedFormDialog } from "../src/features/feeds/FeedFormDialog";
import { createFeed, testFeed } from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  createFeed: vi.fn(),
  testFeed: vi.fn(),
}));

describe("feed source types", () => {
  it("uses the declared anime name when creating a single-anime feed", async () => {
    vi.mocked(createFeed).mockResolvedValue({} as never);
    vi.mocked(testFeed).mockResolvedValue({
      status: "success",
      entry_count: 0,
      preview_titles: [],
      error_code: null,
    });
    const onClose = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <FeedFormDialog open onClose={onClose} />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "单一动画" }));
    fireEvent.change(screen.getByRole("textbox", { name: "动画名称" }), {
      target: { value: "胆大党 第二季" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "订阅地址" }), {
      target: { value: "https://feed.test/rss" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存订阅源" }));

    await waitFor(() => expect(createFeed).toHaveBeenCalledWith(expect.objectContaining({
      name: "胆大党 第二季",
      source_type: "single_anime",
      url: "https://feed.test/rss",
    })));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
