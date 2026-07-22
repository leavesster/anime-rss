import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, ChevronRight, RadioTower } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  bindCatalogTitles,
  createSubscription,
  type Anime,
  type EpisodeGroup,
  type Subscription,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { ErrorBanner, SuccessBanner } from "../../shared/components/Feedback";
import { AddAnimeDialog } from "./AddAnimeDialog";

type DiscoveredSeries = {
  seriesKey: string;
  seriesIdentity: string;
  animeId: string | null;
  matchStatus: string;
  title: string;
  titleVariants: string[];
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
  const [matchTarget, setMatchTarget] = useState<DiscoveredSeries | null>(null);
  const [followedTitle, setFollowedTitle] = useState<string | null>(null);
  const discovered = useMemo(() => {
    const subscribedAnimeIds = new Set(subscriptions.map((item) => item.anime_id));
    const bySeries = new Map<string, DiscoveredSeries>();
    for (const group of groups) {
      if (group.anime_id && subscribedAnimeIds.has(group.anime_id)) continue;
      const current = bySeries.get(group.series_identity);
      if (current) {
        current.episodeCount += 1;
        current.candidateCount += group.candidate_count;
        current.titleVariants = [...new Set([
          ...current.titleVariants,
          ...group.candidates.flatMap((candidate) => candidate.title_variants),
        ])];
      } else {
        const titleVariants = [
          ...new Set(group.candidates.flatMap((candidate) => candidate.title_variants)),
        ];
        bySeries.set(group.series_identity, {
          seriesKey: group.series_key,
          seriesIdentity: group.series_identity,
          animeId: group.anime_id,
          matchStatus: group.catalog_match_status,
          title: anime.find((item) => item.id === group.anime_id)?.primary_title ?? group.series_title,
          titleVariants: titleVariants.length > 0 ? titleVariants : [group.series_title],
          episodeCount: 1,
          candidateCount: group.candidate_count,
        });
      }
    }
    return [...bySeries.values()];
  }, [anime, groups, subscriptions]);
  const follow = useMutation({
    mutationFn: async ({ animeRecord, titles }: { animeRecord: Anime; titles?: string[] }) => {
      if (titles) await bindCatalogTitles(animeRecord.id, titles);
      return createSubscription({
        anime_id: animeRecord.id,
        aliases: [],
        save_path: null,
        use_global_rules: true,
        rules: null,
      });
    },
    onSuccess: async (_subscription, variables) => {
      setFollowedTitle(variables.animeRecord.primary_title);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["anime"] }),
        queryClient.invalidateQueries({ queryKey: ["subscriptions"] }),
        queryClient.invalidateQueries({ queryKey: ["episode-groups"] }),
        queryClient.invalidateQueries({ queryKey: ["selection-slots"] }),
      ]);
    },
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: ["anime"] });
    },
  });

  if (discovered.length === 0 && !follow.isSuccess) return null;

  return (
    <section className="data-section discovered-series-section">
      <div className="section-heading"><div><h2>RSS 已发现</h2><p>已识别、尚未建立追番的动画。</p></div><span className="candidate-count">{discovered.length} 部</span></div>
      {follow.isError && <ErrorBanner message={follow.error.message} />}
      {follow.isSuccess && followedTitle && <SuccessBanner message={`已合并到《${followedTitle}》并开始追番。`} />}
      <div className="discovered-series-list">{discovered.map((series) => (
        <article key={series.seriesIdentity}>
          <Link className="discovered-series-link" to={`/candidates?series=${encodeURIComponent(series.seriesIdentity)}`} aria-label={`查看 ${series.title} 的识别结果`}>
            <span className="subscription-mark"><RadioTower size={18} /></span>
            <div><strong>{series.title}</strong><small>{series.episodeCount} 集 · {series.candidateCount} 个候选 · {series.matchStatus === "matched" ? "已关联动画目录" : "待匹配动画"}</small></div>
            <ChevronRight size={17} />
          </Link>
          <Button size="small" variant="primary" icon={<BookOpenCheck size={15} />} disabled={follow.isPending} onClick={() => {
            const animeRecord = series.animeId ? anime.find((item) => item.id === series.animeId) : undefined;
            if (animeRecord) follow.mutate({ animeRecord });
            else setMatchTarget(series);
          }}>{follow.isPending && follow.variables?.animeRecord.id === series.animeId ? "创建中" : series.animeId ? "开始追番" : "匹配并追番"}</Button>
        </article>
      ))}</div>
      {matchTarget && <AddAnimeDialog initialMode="bangumi" initialTitle={matchTarget.title} onClose={() => setMatchTarget(null)} onSelected={async (animeRecord) => { await follow.mutateAsync({ animeRecord, titles: matchTarget.titleVariants }); }} />}
    </section>
  );
}
