import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "../src/app/AuthGate";
import { getAuthStatus, getInstanceSettings, setupAdministrator } from "../src/generated/api/client";

vi.mock("../src/generated/api/client", () => ({
  ApiError: class ApiError extends Error {},
  getAuthStatus: vi.fn(),
  getInstanceSettings: vi.fn(),
  login: vi.fn(),
  setupAdministrator: vi.fn(),
}));

describe("authentication gate", () => {
  beforeEach(() => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      enabled: true,
      setup_required: true,
      authenticated: false,
      username: null,
    });
    vi.mocked(setupAdministrator).mockResolvedValue({
      username: "admin",
      expires_at: "2026-08-21T00:00:00Z",
    });
    vi.mocked(getInstanceSettings).mockResolvedValue({
      timezone: "Asia/Shanghai",
      interface_language: "zh-CN",
      missing_episode_grace_hours: 24,
      setup_completed_steps: [],
      setup_completed: false,
      version: 0,
      updated_at: null,
    });
  });

  it("requires matching first-run credentials before setup", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AuthGate><div>protected application</div></AuthGate>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "设置管理员" })).toBeInTheDocument();
    const passwords = screen.getAllByLabelText(/密码/);
    fireEvent.change(passwords[0], { target: { value: "long-enough-password" } });
    fireEvent.change(passwords[1], { target: { value: "different-password" } });
    expect(screen.getByText("两次输入的密码不一致")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成设置" })).toBeDisabled();

    fireEvent.change(passwords[1], { target: { value: "long-enough-password" } });
    fireEvent.click(screen.getByRole("button", { name: "完成设置" }));
    await waitFor(() => {
      expect(setupAdministrator).toHaveBeenCalledWith("admin", "long-enough-password");
    });
  });
});
