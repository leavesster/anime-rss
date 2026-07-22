import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "../src/shared/components/StatusBadge";
import { formatInterval, truncateHash } from "../src/shared/lib/format";

describe("presentation helpers", () => {
  it("shows administrator-facing status labels", () => {
    render(<StatusBadge status="auth_failed" />);

    expect(screen.getByText("认证失败")).toBeInTheDocument();
  });

  it("shows feed entry identification and processing labels", () => {
    render(<><StatusBadge status="strong" /><StatusBadge status="weak" /><StatusBadge status="resolved" /><StatusBadge status="unresolved" /></>);

    expect(screen.getByText("有 GUID 标识")).toBeInTheDocument();
    expect(screen.getByText("通过标题内容标识")).toBeInTheDocument();
    expect(screen.getByText("已处理")).toBeInTheDocument();
    expect(screen.getByText("待处理")).toBeInTheDocument();
  });

  it("formats feed intervals and long hashes", () => {
    expect(formatInterval(900)).toBe("15 分钟");
    expect(truncateHash("0123456789abcdef0123456789abcdef")).toBe("0123456789…9abcdef");
  });
});
