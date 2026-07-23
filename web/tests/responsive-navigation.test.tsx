import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../src/app/AppShell";
import { getReadiness, listNotifications } from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  getReadiness: vi.fn(),
  listNotifications: vi.fn(),
}));

afterEach(cleanup);

describe("responsive navigation", () => {
  it("keeps five primary mobile destinations and moves management pages into more", async () => {
    vi.mocked(getReadiness).mockResolvedValue({ status: "ready" } as never);
    vi.mocked(listNotifications).mockResolvedValue([{
      id: "notification-1",
      read_at: null,
    } as never]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/operations"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="*" element={<span>当前页面</span>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const mobileNav = screen.getByRole("navigation", { name: "移动端导航" });
    expect(within(mobileNav).getAllByRole("link")).toHaveLength(4);
    expect(within(mobileNav).getByRole("button", { name: /更多/ })).toHaveAttribute("aria-expanded", "false");
    expect(within(mobileNav).getAllByRole("link").map((item) => item.textContent)).toEqual(["首页", "追番", "版本", "下载"]);
    expect(await within(mobileNav).findByTitle("当前载入消息中 1 条未读")).toHaveTextContent("1");

    fireEvent.click(within(mobileNav).getByRole("button", { name: /更多/ }));
    const dialog = screen.getByRole("dialog", { name: "更多页面" });
    expect(within(dialog).getAllByRole("link").map((item) => item.textContent)).toEqual(["订阅源", "种子列表", "运行", "系统1 条未读"]);

    fireEvent.click(within(dialog).getByRole("link", { name: /系统/ }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "更多页面" })).not.toBeInTheDocument());
  });
});
