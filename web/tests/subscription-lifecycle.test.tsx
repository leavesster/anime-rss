import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LifecycleMenu } from "../src/features/subscriptions/LifecycleMenu";

afterEach(cleanup);

describe("subscription lifecycle menu", () => {
  it("offers completed and archived transitions for a following subscription", () => {
    const onChange = vi.fn();
    render(<LifecycleMenu state="following" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "订阅生命周期操作" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "标记完结" }));
    expect(onChange).toHaveBeenCalledWith("completed");
  });

  it("restores an archived subscription through the legal paused state", () => {
    const onChange = vi.fn();
    render(<LifecycleMenu state="archived" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "订阅生命周期操作" }));
    expect(screen.queryByRole("menuitem", { name: "重新追番" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "恢复为暂停" }));
    expect(onChange).toHaveBeenCalledWith("paused");
  });
});
