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

  it("distinguishes available backfill from future manual selection", () => {
    render(<SelectionLogicPanel />);

    expect(screen.getByText("已支持历史回填逐集确认。")).toBeInTheDocument();
    expect(screen.getByText(/同集人工改选和撤换既有决策将在后续阶段实现/)).toBeInTheDocument();
  });
});
