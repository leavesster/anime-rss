import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SelectionLogicPanel } from "../src/features/subscriptions/SelectionLogicPanel";

afterEach(cleanup);

describe("selection logic panel", () => {
  it("shows the implemented automatic flow in evaluation order", () => {
    render(<SelectionLogicPanel />);

    expect(screen.getAllByTestId("selection-step").map((step) => step.textContent)).toEqual([
      expect.stringContaining("硬过滤"),
      expect.stringContaining("依次比较"),
      expect.stringContaining("等待或决定"),
      expect.stringContaining("版本升级"),
    ]);
  });

  it("shows the implemented manual correction boundary", () => {
    render(<SelectionLogicPanel />);

    expect(screen.getByText("已支持标题确认、历史回填和逐集改选。")).toBeInTheDocument();
    expect(screen.getByText(/人工替换保留旧决策/)).toBeInTheDocument();
  });
});
