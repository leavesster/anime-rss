import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SelectionLogicPanel } from "../src/features/subscriptions/SelectionLogicPanel";

afterEach(cleanup);

describe("selection logic panel", () => {
  it("shows the implemented automatic flow in evaluation order", () => {
    render(<SelectionLogicPanel />);

    expect(screen.getAllByTestId("selection-step").map((step) => step.textContent)).toEqual([
      expect.stringContaining("直接排除"),
      expect.stringContaining("依次比较"),
      expect.stringContaining("等待或决定"),
      expect.stringContaining("版本升级"),
    ]);
  });

  it("shows the implemented manual correction boundary", () => {
    render(<SelectionLogicPanel />);

    expect(screen.getByText("已支持标题确认、补番和逐集改选。")).toBeInTheDocument();
    expect(screen.getByText(/手动替换会保留之前的选择记录/)).toBeInTheDocument();
  });
});
