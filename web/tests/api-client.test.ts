import { afterEach, describe, expect, it, vi } from "vitest";


function supportRelativeRequests() {
  const NativeRequest = Request;
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        const resolved =
          typeof input === "string" && input.startsWith("/")
            ? new URL(input, window.location.origin)
            : input;
        super(resolved, init);
      }
    },
  );
}


afterEach(() => {
  vi.resetModules();
  vi.unstubAllGlobals();
  document.cookie = "anime_rss_csrf=; Max-Age=0; path=/";
});


describe("API client HTTP contracts", () => {
  it("adds CSRF and a UUID idempotency key to mutations", async () => {
    supportRelativeRequests();
    document.cookie = "anime_rss_csrf=csrf-token; path=/";
    const fetchMock = vi.fn(async (request: Request) => {
      expect(request.headers.get("x-csrf-token")).toBe("csrf-token");
      expect(request.headers.get("idempotency-key")).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
      return new Response(JSON.stringify({ id: "feed-1" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { createFeed } = await import("../src/generated/api/client");

    await createFeed({
      name: "Contract Feed",
      url: "https://feed.test/rss",
      source_type: "aggregate",
      interval_seconds: 600,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("treats only setup-required 428 responses as authentication state", async () => {
    supportRelativeRequests();
    const fetchMock = vi
      .fn<(request: Request) => Promise<Response>>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            code: "if_match_required",
            message: "If-Match header is required",
            detail: "If-Match header is required",
          }),
          { status: 428, headers: { "content-type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            code: "administrator_setup_required",
            message: "administrator setup required",
            detail: "administrator setup required",
          }),
          { status: 428, headers: { "content-type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { getAuthStatus, listFeeds } = await import("../src/generated/api/client");
    const authRequired = vi.fn();
    window.addEventListener("anime-rss-auth-required", authRequired);

    await expect(listFeeds()).rejects.toMatchObject({ status: 428 });
    expect(authRequired).not.toHaveBeenCalled();
    await expect(getAuthStatus()).rejects.toMatchObject({ status: 428 });
    expect(authRequired).toHaveBeenCalledTimes(1);

    window.removeEventListener("anime-rss-auth-required", authRequired);
  });
});
