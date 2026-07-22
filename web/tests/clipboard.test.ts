import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "../src/shared/lib/clipboard";

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const execCommandDescriptor = Object.getOwnPropertyDescriptor(document, "execCommand");

afterEach(() => {
  vi.restoreAllMocks();
  if (clipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  } else {
    Reflect.deleteProperty(navigator, "clipboard");
  }
  if (execCommandDescriptor) {
    Object.defineProperty(document, "execCommand", execCommandDescriptor);
  } else {
    Reflect.deleteProperty(document, "execCommand");
  }
});

describe("copy text", () => {
  it("falls back to document copying outside secure clipboard contexts", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    const execute = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { configurable: true, value: execute });

    await expect(copyText("LAN title")).resolves.toBe(true);
    expect(execute).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).not.toBeInTheDocument();
  });

  it("cleans up when legacy copying is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn(() => {
        throw new Error("copy unavailable");
      }),
    });

    await expect(copyText("LAN title")).resolves.toBe(false);
    expect(document.querySelector("textarea")).not.toBeInTheDocument();
  });
});
