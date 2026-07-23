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
export type EpisodeGroup = components["schemas"]["EpisodeGroupResponse"];
export type Candidate = components["schemas"]["CandidateResponse"];
export type UnmatchedRelease = components["schemas"]["UnmatchedReleaseResponse"];
export type RecognitionRerun = components["schemas"]["RecognitionRerunResponse"];
export type Anime = components["schemas"]["AnimeResponse"];
export type BangumiAnime = components["schemas"]["BangumiAnimeResponse"];
export type CatalogSearch = components["schemas"]["CatalogSearchResponse"];
export type Subscription = components["schemas"]["SubscriptionResponse"];
export type SubscriptionCreate = components["schemas"]["SubscriptionCreateRequest"];
export type SubscriptionPatch = components["schemas"]["SubscriptionPatchRequest"];
export type PreferenceProfile = components["schemas"]["PreferenceProfileResponse"];
export type PreferenceRules = components["schemas"]["PreferenceRulesModel"];
export type EpisodeSlot = components["schemas"]["EpisodeSlotResponse"];
export type Decision = components["schemas"]["DecisionResponse"];
export type BackfillPreview = components["schemas"]["BackfillPreviewResponse"];
export type ManualAction = components["schemas"]["ManualActionResponse"];
export type DownloadConfig = components["schemas"]["DownloadConfigResponse"];
export type DownloadConfigRequest = components["schemas"]["DownloadConfigRequest"];
export type DownloadConnection = components["schemas"]["DownloadConnectionResponse"];
export type DownloadTask = components["schemas"]["DownloadTaskResponse"];
export type DownloadCycle = components["schemas"]["DownloadCycleResponse"];
export type OperationsOverview = components["schemas"]["OperationsOverviewResponse"];
export type ScheduledJob = components["schemas"]["ScheduledJobResponse"];
export type JobRun = components["schemas"]["JobRunResponse"];
export type AuditEvent = components["schemas"]["AuditEventResponse"];
export type ReleaseRemap = components["schemas"]["ReleaseRemapRequest"];
export type AuthStatus = components["schemas"]["AuthStatusResponse"];
export type Session = components["schemas"]["SessionResponse"];
export type NotificationConfig = components["schemas"]["NotificationConfigResponse"];
export type NotificationConfigRequest = components["schemas"]["NotificationConfigRequest"];
export type Notification = components["schemas"]["NotificationResponse"];
export type Backup = components["schemas"]["BackupResponse"];
export type Restore = components["schemas"]["RestoreResponse"];
export type InstanceSettings = components["schemas"]["InstanceSettingsResponse"];
export type InstanceSettingsUpdate = components["schemas"]["InstanceSettingsUpdateRequest"];
export type AnimeScheduleUpdate = components["schemas"]["AnimeScheduleUpdateRequest"];
export type ExpectedEpisode = components["schemas"]["ExpectedEpisodeResponse"];
export type CalendarDay = components["schemas"]["CalendarDayResponse"];
export type ScheduleSync = components["schemas"]["ScheduleSyncResponse"];
export type EpisodeScheduleOverride =
  components["schemas"]["EpisodeScheduleOverrideResponse"];
export type EpisodeScheduleOverrideRequest =
  components["schemas"]["EpisodeScheduleOverrideRequest"];
export type SeasonalOverview = components["schemas"]["SeasonalOverviewResponse"];
export type SeasonalAnime = components["schemas"]["SeasonalAnimeResponse"];
export type SeasonalAction = components["schemas"]["SeasonalActionResponse"];

const client = createClient<paths>({ baseUrl: "" });

function cookieValue(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${encodeURIComponent(name)}=`;
  const value = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : null;
}

client.use({
  onRequest({ request }) {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      const token = cookieValue("anime_rss_csrf");
      if (token) request.headers.set("x-csrf-token", token);
      if (!request.headers.has("idempotency-key")) {
        request.headers.set("idempotency-key", crypto.randomUUID());
      }
    }
    return request;
  },
  async onResponse({ response }) {
    let setupRequired = false;
    if (response.status === 428) {
      const payload = (await response.clone().json().catch(() => null)) as unknown;
      setupRequired =
        typeof payload === "object" &&
        payload !== null &&
        "code" in payload &&
        payload.code === "administrator_setup_required";
    }
    if ((response.status === 401 || setupRequired) && typeof window !== "undefined") {
      window.dispatchEvent(new Event("anime-rss-auth-required"));
    }
    return response;
  },
});

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function errorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "message" in error) {
    const message = error.message;
    if (typeof message === "string") return message;
  }
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

export async function getAuthStatus(): Promise<AuthStatus> {
  return unwrap(await client.GET("/api/v1/auth/status"));
}

export async function setupAdministrator(username: string, password: string): Promise<Session> {
  return unwrap(await client.POST("/api/v1/auth/setup", { body: { username, password } }));
}

export async function login(username: string, password: string): Promise<Session> {
  return unwrap(await client.POST("/api/v1/auth/login", { body: { username, password } }));
}

export async function logout(): Promise<void> {
  const result = await client.POST("/api/v1/auth/logout");
  if (!result.response.ok) {
    throw new ApiError("退出登录失败", result.response.status);
  }
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
        header: { "If-Match": version },
      },
      body: payload,
    }),
  );
}

export async function deleteFeed(feedId: string, version: number): Promise<void> {
  const result = await client.DELETE("/api/v1/feeds/{feed_id}", {
    params: {
      path: { feed_id: feedId },
      header: { "If-Match": version },
    },
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

export async function listEpisodeGroups(): Promise<EpisodeGroup[]> {
  return unwrap(
    await client.GET("/api/v1/recognition/episode-groups", {
      params: { query: { limit: 200 } },
    }),
  );
}

export async function listUnmatchedReleases(): Promise<UnmatchedRelease[]> {
  return unwrap(
    await client.GET("/api/v1/recognition/unmatched", {
      params: { query: { limit: 200 } },
    }),
  );
}

export async function dismissRelease(releaseId: string): Promise<void> {
  const result = await client.POST("/api/v1/recognition/releases/{release_id}/dismiss", {
    params: { path: { release_id: releaseId } },
  });
  if (result.error !== undefined) {
    throw new ApiError(errorMessage(result.error), result.response.status);
  }
}

export async function confirmCandidate(candidateId: string): Promise<Candidate> {
  return unwrap(
    await client.POST("/api/v1/recognition/candidates/{candidate_id}/confirm", {
      params: { path: { candidate_id: candidateId } },
    }),
  );
}

export async function remapRelease(releaseId: string, payload: ReleaseRemap): Promise<Candidate> {
  return unwrap(
    await client.POST("/api/v1/recognition/releases/{release_id}/remap", {
      params: { path: { release_id: releaseId } },
      body: payload,
    }),
  );
}

export async function rerunRecognition(releaseId: string): Promise<RecognitionRerun> {
  return unwrap(
    await client.POST("/api/v1/recognition/releases/{release_id}/rerun", {
      params: { path: { release_id: releaseId } },
    }),
  );
}

export async function listAnime(): Promise<Anime[]> {
  return unwrap(await client.GET("/api/v1/catalog/anime"));
}

export async function getSeasonalOverview(
  year: number,
  quarter: number,
): Promise<SeasonalOverview> {
  return unwrap(
    await client.GET("/api/v1/seasonal", {
      params: { query: { year, quarter } },
    }),
  );
}

export async function refreshSeasonalOverview(
  year: number,
  quarter: number,
): Promise<SeasonalOverview> {
  return unwrap(
    await client.POST("/api/v1/seasonal/refresh", {
      params: { query: { year, quarter } },
    }),
  );
}

export async function followSeasonalAnime(bangumiId: number): Promise<SeasonalAction> {
  return unwrap(
    await client.POST("/api/v1/seasonal/{bangumi_id}/follow", {
      params: { path: { bangumi_id: bangumiId } },
    }),
  );
}

export async function markSeasonalAnimeWatched(bangumiId: number): Promise<SeasonalAction> {
  return unwrap(
    await client.POST("/api/v1/seasonal/{bangumi_id}/watched", {
      params: { path: { bangumi_id: bangumiId } },
    }),
  );
}

export async function dismissSeasonalAnime(bangumiId: number): Promise<SeasonalAction> {
  return unwrap(
    await client.POST("/api/v1/seasonal/{bangumi_id}/dismiss", {
      params: { path: { bangumi_id: bangumiId } },
    }),
  );
}

export async function createLocalAnime(title: string, aliases: string[]): Promise<Anime> {
  return unwrap(await client.POST("/api/v1/catalog/anime", { body: { title, aliases } }));
}

export async function searchBangumi(query: string): Promise<CatalogSearch> {
  return unwrap(
    await client.GET("/api/v1/catalog/bangumi/search", {
      params: { query: { query } },
    }),
  );
}

export async function importBangumi(bangumiId: number): Promise<Anime> {
  return unwrap(
    await client.POST("/api/v1/catalog/bangumi/{bangumi_id}/import", {
      params: { path: { bangumi_id: bangumiId } },
    }),
  );
}

export async function bindCatalogTitles(animeId: string, titles: string[]): Promise<Anime> {
  return unwrap(
    await client.POST("/api/v1/catalog/anime/{anime_id}/title-bindings", {
      params: { path: { anime_id: animeId } },
      body: { titles },
    }),
  );
}

export async function updateAnimeSchedule(
  animeId: string,
  version: number,
  payload: AnimeScheduleUpdate,
): Promise<Anime> {
  return unwrap(
    await client.PUT("/api/v1/catalog/anime/{anime_id}/schedule", {
      params: {
        path: { anime_id: animeId },
        header: { "If-Match": version },
      },
      body: payload,
    }),
  );
}

export async function listSubscriptions(): Promise<Subscription[]> {
  return unwrap(await client.GET("/api/v1/subscriptions"));
}

export async function createSubscription(payload: SubscriptionCreate): Promise<Subscription> {
  return unwrap(await client.POST("/api/v1/subscriptions", { body: payload }));
}

export async function updateSubscription(
  subscriptionId: string,
  version: number,
  payload: SubscriptionPatch,
): Promise<Subscription> {
  return unwrap(
    await client.PATCH("/api/v1/subscriptions/{subscription_id}", {
      params: {
        path: { subscription_id: subscriptionId },
        header: { "If-Match": version },
      },
      body: payload,
    }),
  );
}

export async function getGlobalPreferences(): Promise<PreferenceProfile> {
  return unwrap(await client.GET("/api/v1/subscriptions/preferences/global"));
}

export async function saveGlobalPreferences(
  rules: PreferenceRules,
  version: number,
): Promise<PreferenceProfile> {
  return unwrap(
    await client.PUT("/api/v1/subscriptions/preferences/global", {
      params: { header: { "If-Match": version } },
      body: rules,
    }),
  );
}

export async function listSelectionSlots(subscriptionId?: string): Promise<EpisodeSlot[]> {
  return unwrap(
    await client.GET("/api/v1/selection/episodes", {
      params: { query: { subscription_id: subscriptionId, limit: 200 } },
    }),
  );
}

export async function listDecisions(subscriptionId?: string): Promise<Decision[]> {
  return unwrap(
    await client.GET("/api/v1/selection/decisions", {
      params: { query: { subscription_id: subscriptionId, limit: 200 } },
    }),
  );
}

export async function previewBackfill(subscriptionId: string): Promise<BackfillPreview[]> {
  return unwrap(
    await client.GET(
      "/api/v1/selection/subscriptions/{subscription_id}/backfill-preview",
      { params: { path: { subscription_id: subscriptionId } } },
    ),
  );
}

export async function commitBackfill(
  subscriptionId: string,
  episodeKeys: string[],
): Promise<{ processed: number }> {
  return unwrap(
    await client.POST(
      "/api/v1/selection/subscriptions/{subscription_id}/backfill-commit",
      {
        params: { path: { subscription_id: subscriptionId } },
        body: { episode_keys: episodeKeys },
      },
    ),
  );
}

export async function selectCandidate(
  subscriptionId: string,
  candidateId: string,
  options: { replace_existing?: boolean; override_filters?: boolean } = {},
): Promise<{ decision_id: string }> {
  return unwrap(
    await client.POST(
      "/api/v1/selection/subscriptions/{subscription_id}/candidates/{candidate_id}/select",
      {
        params: { path: { subscription_id: subscriptionId, candidate_id: candidateId } },
        body: {
          replace_existing: options.replace_existing ?? false,
          override_filters: options.override_filters ?? false,
        },
      },
    ),
  );
}

export async function rejectCandidate(
  subscriptionId: string,
  candidateId: string,
): Promise<ManualAction> {
  return unwrap(
    await client.POST(
      "/api/v1/selection/subscriptions/{subscription_id}/candidates/{candidate_id}/reject",
      { params: { path: { subscription_id: subscriptionId, candidate_id: candidateId } } },
    ),
  );
}

export async function resetEpisode(
  subscriptionId: string,
  episodeKey: string,
): Promise<ManualAction> {
  return unwrap(
    await client.POST(
      "/api/v1/selection/subscriptions/{subscription_id}/episodes/{episode_key}/reset",
      { params: { path: { subscription_id: subscriptionId, episode_key: episodeKey } } },
    ),
  );
}

export async function markEpisodeAcquired(
  subscriptionId: string,
  episodeKey: string,
): Promise<ManualAction> {
  return unwrap(
    await client.POST(
      "/api/v1/selection/subscriptions/{subscription_id}/episodes/{episode_key}/acquired-elsewhere",
      { params: { path: { subscription_id: subscriptionId, episode_key: episodeKey } } },
    ),
  );
}

export async function listManualActions(subscriptionId?: string): Promise<ManualAction[]> {
  return unwrap(
    await client.GET("/api/v1/selection/manual-actions", {
      params: { query: { subscription_id: subscriptionId, limit: 200 } },
    }),
  );
}

export async function getDownloadConfig(): Promise<DownloadConfig | null> {
  return unwrap(await client.GET("/api/v1/downloads/config"));
}

export async function saveDownloadConfig(
  payload: DownloadConfigRequest,
  version = 0,
): Promise<DownloadConfig> {
  return unwrap(
    await client.PUT("/api/v1/downloads/config", {
      params: { header: { "If-Match": version } },
      body: payload,
    }),
  );
}

export async function testDownloadConnection(): Promise<DownloadConnection> {
  return unwrap(await client.POST("/api/v1/downloads/config/test"));
}

export async function listDownloadTasks(): Promise<DownloadTask[]> {
  return unwrap(
    await client.GET("/api/v1/downloads/tasks", {
      params: { query: { limit: 200 } },
    }),
  );
}

export async function submitReleaseDownload(releaseId: string): Promise<DownloadTask> {
  return unwrap(
    await client.POST("/api/v1/downloads/releases/{release_id}/submit", {
      params: { path: { release_id: releaseId } },
    }),
  );
}

export async function processDownloads(): Promise<DownloadCycle> {
  return unwrap(await client.POST("/api/v1/downloads/process"));
}

export async function retryDownloadTask(taskId: string): Promise<DownloadTask> {
  return unwrap(
    await client.POST("/api/v1/downloads/tasks/{task_id}/retry", {
      params: { path: { task_id: taskId } },
    }),
  );
}

export async function getOperationsOverview(): Promise<OperationsOverview> {
  return unwrap(await client.GET("/api/v1/operations/overview"));
}

export async function listScheduledJobs(): Promise<ScheduledJob[]> {
  return unwrap(
    await client.GET("/api/v1/operations/jobs", { params: { query: { limit: 200 } } }),
  );
}

export async function listJobRuns(): Promise<JobRun[]> {
  return unwrap(
    await client.GET("/api/v1/operations/runs", { params: { query: { limit: 100 } } }),
  );
}

export async function runSchedulerNow(): Promise<{ processed: number }> {
  return unwrap(await client.POST("/api/v1/operations/run-now"));
}

export async function syncSchedule(): Promise<ScheduleSync> {
  return unwrap(await client.POST("/api/v1/schedule/sync"));
}

export async function listScheduleCalendar(days = 8): Promise<CalendarDay[]> {
  return unwrap(
    await client.GET("/api/v1/schedule/calendar", { params: { query: { days } } }),
  );
}

export async function listMissingEpisodes(): Promise<ExpectedEpisode[]> {
  return unwrap(
    await client.GET("/api/v1/schedule/missing", { params: { query: { limit: 100 } } }),
  );
}

export async function getScheduleOverview(): Promise<{
  calendar: CalendarDay[];
  missing: ExpectedEpisode[];
}> {
  const [calendar, missing] = await Promise.all([
    listScheduleCalendar(),
    listMissingEpisodes(),
  ]);
  return { calendar, missing };
}

export async function listAnimeEpisodeHistory(animeId: string): Promise<ExpectedEpisode[]> {
  return unwrap(
    await client.GET("/api/v1/schedule/anime/{anime_id}/episodes", {
      params: { path: { anime_id: animeId }, query: { limit: 200 } },
    }),
  );
}

export async function listEpisodeScheduleOverrides(
  animeId: string,
): Promise<EpisodeScheduleOverride[]> {
  return unwrap(
    await client.GET("/api/v1/schedule/anime/{anime_id}/overrides", {
      params: { path: { anime_id: animeId } },
    }),
  );
}

export async function saveEpisodeScheduleOverride(
  animeId: string,
  episodeKey: string,
  payload: EpisodeScheduleOverrideRequest,
  version = 0,
): Promise<EpisodeScheduleOverride> {
  return unwrap(
    await client.PUT("/api/v1/schedule/anime/{anime_id}/overrides/{episode_key}", {
      params: {
        path: { anime_id: animeId, episode_key: episodeKey },
        header: { "If-Match": version },
      },
      body: payload,
    }),
  );
}

export async function deleteEpisodeScheduleOverride(
  animeId: string,
  episodeKey: string,
  version: number,
): Promise<void> {
  const result = await client.DELETE(
    "/api/v1/schedule/anime/{anime_id}/overrides/{episode_key}",
    {
      params: {
        path: { anime_id: animeId, episode_key: episodeKey },
        header: { "If-Match": version },
      },
    },
  );
  if (result.error !== undefined) {
    throw new ApiError(errorMessage(result.error), result.response.status);
  }
}

export async function refreshSchedule(): Promise<{
  calendar: CalendarDay[];
  missing: ExpectedEpisode[];
}> {
  await syncSchedule();
  return getScheduleOverview();
}

export async function listAuditEvents(): Promise<AuditEvent[]> {
  return unwrap(
    await client.GET("/api/v1/audit/events", { params: { query: { limit: 100 } } }),
  );
}

export async function getNotificationConfig(): Promise<NotificationConfig | null> {
  return unwrap(await client.GET("/api/v1/notifications/config"));
}

export async function saveNotificationConfig(
  payload: NotificationConfigRequest,
  version = 0,
): Promise<NotificationConfig> {
  return unwrap(
    await client.PUT("/api/v1/notifications/config", {
      params: { header: { "If-Match": version } },
      body: payload,
    }),
  );
}

export async function testNotificationWebhook(): Promise<void> {
  const result = await client.POST("/api/v1/notifications/config/test");
  if (!result.response.ok) {
    throw new ApiError("Webhook 测试失败", result.response.status);
  }
}

export async function listNotifications(): Promise<Notification[]> {
  return unwrap(
    await client.GET("/api/v1/notifications", { params: { query: { limit: 100 } } }),
  );
}

export async function markNotificationRead(notificationId: string): Promise<Notification> {
  return unwrap(
    await client.POST("/api/v1/notifications/{notification_id}/read", {
      params: { path: { notification_id: notificationId } },
    }),
  );
}

export async function listBackups(): Promise<Backup[]> {
  return unwrap(await client.GET("/api/v1/system/backups"));
}

export async function getInstanceSettings(): Promise<InstanceSettings> {
  return unwrap(await client.GET("/api/v1/system/settings"));
}

export async function saveInstanceSettings(
  payload: InstanceSettingsUpdate,
  version: number,
): Promise<InstanceSettings> {
  return unwrap(
    await client.PUT("/api/v1/system/settings", {
      params: { header: { "If-Match": version } },
      body: payload,
    }),
  );
}

export async function markSetupStep(step: string): Promise<InstanceSettings> {
  return unwrap(
    await client.POST("/api/v1/system/settings/setup/{step}", {
      params: { path: { step } },
    }),
  );
}

export async function createBackup(): Promise<Backup> {
  return unwrap(await client.POST("/api/v1/system/backups"));
}

export async function stageRestore(file: File): Promise<Restore> {
  const headers = new Headers({ "content-type": "application/zip" });
  const csrf = cookieValue("anime_rss_csrf");
  if (csrf) headers.set("x-csrf-token", csrf);
  const response = await fetch("/api/v1/system/backups/restore/stage", {
    method: "POST",
    headers,
    body: file,
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as unknown;
    throw new ApiError(errorMessage(error), response.status);
  }
  return (await response.json()) as Restore;
}
