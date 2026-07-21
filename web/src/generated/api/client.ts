import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Feed = components["schemas"]["FeedResponse"];
export type FeedCreate = components["schemas"]["FeedCreateRequest"];
export type FeedPatch = components["schemas"]["FeedPatchRequest"];
export type FeedTest = components["schemas"]["FeedTestResponse"];
export type FeedEntry = components["schemas"]["FeedEntryResponse"];
export type FeedFetch = components["schemas"]["FeedFetchResponse"];
export type RefreshResult = components["schemas"]["RefreshResponse"];
export type Release = components["schemas"]["ReleaseResponse"];

const client = createClient<paths>({ baseUrl: "" });

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function errorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = error.detail;
    if (typeof detail === "string") return detail;
  }
  return "请求未完成，请稍后重试";
}

function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined) {
    throw new ApiError(errorMessage(result.error), result.response.status);
  }
  if (result.data === undefined) {
    throw new ApiError("服务返回了空响应", result.response.status);
  }
  return result.data;
}

export async function getReadiness(): Promise<Record<string, string>> {
  return unwrap(await client.GET("/api/v1/health/ready"));
}

export async function listFeeds(): Promise<Feed[]> {
  return unwrap(await client.GET("/api/v1/feeds"));
}

export async function createFeed(payload: FeedCreate): Promise<Feed> {
  return unwrap(await client.POST("/api/v1/feeds", { body: payload }));
}

export async function updateFeed(
  feedId: string,
  version: number,
  payload: FeedPatch,
): Promise<Feed> {
  return unwrap(
    await client.PATCH("/api/v1/feeds/{feed_id}", {
      params: {
        path: { feed_id: feedId },
        header: { "if-match": version },
      },
      body: payload,
    }),
  );
}

export async function deleteFeed(feedId: string): Promise<void> {
  const result = await client.DELETE("/api/v1/feeds/{feed_id}", {
    params: { path: { feed_id: feedId } },
  });
  if (result.error !== undefined) {
    throw new ApiError(errorMessage(result.error), result.response.status);
  }
}

export async function testFeed(payload: FeedCreate): Promise<FeedTest> {
  return unwrap(
    await client.POST("/api/v1/feeds/test", {
      body: { url: payload.url, headers: payload.headers },
    }),
  );
}

export async function refreshFeed(feedId: string): Promise<RefreshResult> {
  return unwrap(
    await client.POST("/api/v1/feeds/{feed_id}/refresh", {
      params: { path: { feed_id: feedId } },
    }),
  );
}

export async function listFeedEntries(feedId: string): Promise<FeedEntry[]> {
  return unwrap(
    await client.GET("/api/v1/feeds/{feed_id}/entries", {
      params: { path: { feed_id: feedId }, query: { limit: 100 } },
    }),
  );
}

export async function listFeedFetches(feedId: string): Promise<FeedFetch[]> {
  return unwrap(
    await client.GET("/api/v1/feeds/{feed_id}/fetches", {
      params: { path: { feed_id: feedId }, query: { limit: 100 } },
    }),
  );
}

export async function listReleases(): Promise<Release[]> {
  return unwrap(
    await client.GET("/api/v1/releases", { params: { query: { limit: 200 } } }),
  );
}
