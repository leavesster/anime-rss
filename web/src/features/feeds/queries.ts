import { queryOptions } from "@tanstack/react-query";

import { listFeedEntries, listFeedFetches, listFeeds } from "../../generated/api/client";

export const feedsQuery = queryOptions({ queryKey: ["feeds"], queryFn: listFeeds });

export const feedEntriesQuery = (feedId: string) =>
  queryOptions({ queryKey: ["feeds", feedId, "entries"], queryFn: () => listFeedEntries(feedId) });

export const feedFetchesQuery = (feedId: string) =>
  queryOptions({ queryKey: ["feeds", feedId, "fetches"], queryFn: () => listFeedFetches(feedId) });
