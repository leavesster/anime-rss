import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, RadioTower } from "lucide-react";
import { useMemo } from "react";

import {
  createLocalAnime,
  createSubscription,
  type Anime,
  type EpisodeGroup,
  type Subscription,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { ErrorBanner } from "../../shared/components/Feedback";

type DiscoveredSeries = {
  seriesKey: string;
  title: string;
  episodeCount: number;
  candidateCount: number;
};

export function DiscoveredSeriesSection({
  anime,
  subscriptions,
  groups,
}: {
  anime: Anime[];
  subscriptions: Subscription[];
  groups: EpisodeGroup[];
}) {
  const queryClient = useQueryClient();
  const discovered = useMemo(() => {
    const subscribedKeys = new Set(subscriptions.flatMap((item) => item.match_keys));
    const bySeries = new Map<string, DiscoveredSeries>();
    for (const group of groups) {
      if (subscribedKeys.has(group.series_key)) continue;
      const current = bySeries.get(group.series_key);
      if (current) {
        current.episodeCount += 1;
        current.candidateCount += group.candidate_count;
      } else {
        bySeries.set(group.series_key, {
          seriesKey: group.series_key,
          title: group.series_title,
          episodeCount: 1,
          candidateCount: group.candidate_count,
        });
      }
    }
    return [...bySeries.values()];
  }, [groups, subscriptions]);
  const follow = useMutation({
    mutationFn: async (series: DiscoveredSeries) => {
      const existing = anime.find((item) =>
        item.titles.some((title) => title.normalized === series.seriesKey),
      );
      const animeRecord = existing ?? await createLocalAnime(series.title, []);
      return createSubscription({
        anime_id: animeRecord.id,
        aliases: [],
        save_path: null,
        use_global_rules: true,
        rules: null,
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["anime"] }),
        queryClient.invalidateQueries({ queryKey: ["subscriptions"] }),
        queryClient.invalidateQueries({ queryKey: ["selection-slots"] }),
      ]);
    },
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: ["anime"] });
    },
  });

  if (discovered.length === 0) return null;

  return (
    <section className="data-section discovered-series-section">
      <div className="section-heading"><div><h2>RSS 已发现</h2><p>已识别、尚未建立追番的动画。</p></div><span className="candidate-count">{discovered.length} 部</span></div>
      {follow.isError && <ErrorBanner message={follow.error.message} />}
      <div className="discovered-series-list">{discovered.map((series) => (
        <article key={series.seriesKey}>
          <span className="subscription-mark"><RadioTower size={18} /></span>
          <div><strong>{series.title}</strong><small>{series.episodeCount} 集 · {series.candidateCount} 个候选</small></div>
          <Button size="small" variant="primary" icon={<BookOpenCheck size={15} />} disabled={follow.isPending} onClick={() => follow.mutate(series)}>{follow.isPending && follow.variables?.seriesKey === series.seriesKey ? "创建中" : "开始追番"}</Button>
        </article>
      ))}</div>
    </section>
  );
}
