import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Check, ChevronDown, ChevronRight, ChevronUp, Link2 } from "lucide-react";
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
import "./DiscoveredSeriesSection.css";

type DiscoveredSeries = {
  seriesIdentity: string;
  animeId: string | null;
  matchStatus: string;
  title: string;
  rssTitles: string[];
  titleGroups: string[][];
  episodeCount: number;
  candidateCount: number;
};

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function uniqueTitleGroups(groups: string[][]): string[][] {
  const unique = new Map<string, string[]>();
  for (const group of groups) {
    const titles = uniqueStrings(group);
    if (titles.length === 0) continue;
    unique.set([...titles].sort().join("\u0000"), titles);
  }
  return [...unique.values()];
}

function matchStatusLabel(series: DiscoveredSeries): string {
  if (series.animeId) return "已匹配到动画";
  return series.matchStatus === "ambiguous" ? "匹配到多部动画" : "未匹配到动画";
}

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
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedSeries, setExpandedSeries] = useState<Set<string>>(new Set());
  const [selectedSeries, setSelectedSeries] = useState<Set<string>>(new Set());
  const [matchTargets, setMatchTargets] = useState<DiscoveredSeries[] | null>(null);
  const [matchedMessage, setMatchedMessage] = useState<string | null>(null);
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
        current.rssTitles = uniqueStrings([
          ...current.rssTitles,
          ...group.candidates.map((candidate) => candidate.series_title || group.series_title),
        ]);
        current.titleGroups = uniqueTitleGroups([
          ...current.titleGroups,
          ...group.candidates.map((candidate) => candidate.title_variants),
        ]);
      } else {
        bySeries.set(group.series_identity, {
          seriesIdentity: group.series_identity,
          animeId: group.anime_id,
          matchStatus: group.catalog_match_status,
          title: anime.find((item) => item.id === group.anime_id)?.primary_title ?? group.series_title,
          rssTitles: uniqueStrings(group.candidates.map((candidate) => candidate.series_title || group.series_title)),
          titleGroups: uniqueTitleGroups(group.candidates.map((candidate) => candidate.title_variants)),
          episodeCount: 1,
          candidateCount: group.candidate_count,
        });
      }
    }
    return [...bySeries.values()];
  }, [anime, groups, subscriptions]);
  const selectedMatchTargets = discovered.filter((series) =>
    selectedSeries.has(series.seriesIdentity)
  );
  const match = useMutation({
    mutationFn: async ({ animeRecord, targets }: { animeRecord: Anime; targets: DiscoveredSeries[] }) => {
      for (const target of targets) {
        for (const titles of target.titleGroups) {
          await bindCatalogTitles(animeRecord.id, titles);
        }
      }
      return { animeRecord, count: targets.length };
    },
    onSuccess: async ({ animeRecord, count }) => {
      setMatchedMessage(`已将 ${count} 个 RSS 动画匹配到《${animeRecord.primary_title}》。`);
      setFollowedTitle(null);
      setSelectedSeries(new Set());
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["anime"] }),
        queryClient.invalidateQueries({ queryKey: ["episode-groups"] }),
      ]);
    },
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: ["episode-groups"] });
    },
  });
  const follow = useMutation({
    mutationFn: async (animeRecord: Anime) => ({
      animeRecord,
      subscription: await createSubscription({
        anime_id: animeRecord.id,
        aliases: [],
        save_path: null,
        use_global_rules: true,
        rules: null,
      }),
    }),
    onSuccess: async ({ animeRecord }) => {
      setFollowedTitle(animeRecord.primary_title);
      setMatchedMessage(null);
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

  const toggleSelected = (seriesIdentity: string) => {
    setSelectedSeries((current) => {
      const next = new Set(current);
      if (next.has(seriesIdentity)) next.delete(seriesIdentity);
      else next.add(seriesIdentity);
      return next;
    });
  };
  const toggleSeries = (seriesIdentity: string) => {
    setExpandedSeries((current) => {
      const next = new Set(current);
      if (next.has(seriesIdentity)) next.delete(seriesIdentity);
      else next.add(seriesIdentity);
      return next;
    });
  };

  if (discovered.length === 0 && !follow.isSuccess && !match.isSuccess) return null;

  return (
    <section className="data-section discovered-series-section">
      <div className="section-heading"><div><h2><button className="discovered-section-toggle" type="button" aria-expanded={isExpanded} aria-controls="discovered-series-content" onClick={() => setIsExpanded((current) => !current)}>RSS 动画 {isExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</button></h2><p>先把一个或多个 RSS 动画匹配到 Bangumi 动画，再单独选择是否追番。“未匹配到动画”表示尚未对应上 Bangumi 动画 ID。</p></div><div className="discovered-series-heading-actions">{selectedMatchTargets.length > 0 && <Button size="small" variant="secondary" icon={<Link2 size={15} />} onClick={() => setMatchTargets(selectedMatchTargets)}>匹配所选（{selectedMatchTargets.length}）</Button>}<span className="candidate-count">{discovered.length} 部</span></div></div>
      {isExpanded && <div id="discovered-series-content">
        {matchedMessage && <SuccessBanner message={matchedMessage} />}
        {follow.isError && <ErrorBanner message={follow.error.message} />}
        {follow.isSuccess && followedTitle && <SuccessBanner message={`已合并到《${followedTitle}》并开始追番。`} />}
        <div className="discovered-series-list">{discovered.map((series) => (
          <article className="discovered-series-item" key={series.seriesIdentity}>
            <div className="discovered-series-row">
              <label className="discovered-series-select" title={`选择 ${series.title}`}><input type="checkbox" aria-label={`选择 RSS 动画 ${series.title}`} checked={selectedSeries.has(series.seriesIdentity)} onChange={() => toggleSelected(series.seriesIdentity)} /></label>
              <button className="discovered-series-summary" type="button" aria-expanded={expandedSeries.has(series.seriesIdentity)} aria-controls={`rss-titles-${series.seriesIdentity}`} aria-label={`${expandedSeries.has(series.seriesIdentity) ? "收起" : "展开"}《${series.title}》的 RSS 标题`} onClick={() => toggleSeries(series.seriesIdentity)}>
                <span><strong>{series.title}</strong><small>{series.episodeCount} 集 · {series.candidateCount} 个候选 · {series.rssTitles.length} 个 RSS 标题 · {matchStatusLabel(series)}</small></span>
                {expandedSeries.has(series.seriesIdentity) ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
              </button>
              <div className="discovered-series-actions">{series.animeId ? <Button size="small" variant="primary" icon={<BookOpenCheck size={15} />} disabled={follow.isPending} onClick={() => {
                const animeRecord = anime.find((item) => item.id === series.animeId);
                if (animeRecord) follow.mutate(animeRecord);
              }}>{follow.isPending && follow.variables?.id === series.animeId ? "创建中" : "开始追番"}</Button> : <Button size="small" variant="secondary" icon={<Link2 size={15} />} disabled={match.isPending} onClick={() => setMatchTargets([series])}>匹配</Button>}</div>
            </div>
            {expandedSeries.has(series.seriesIdentity) && <div className="discovered-series-details" id={`rss-titles-${series.seriesIdentity}`}>
              <div><strong>RSS 识别标题</strong><small>{series.animeId ? `以下标题均对应《${series.title}》` : "可勾选多个 RSS 动画，一次匹配到同一部 Bangumi 动画"}</small></div>
              <ul>{series.rssTitles.map((title) => <li key={title}>{title}</li>)}</ul>
              <Link to={`/candidates?series=${encodeURIComponent(series.seriesIdentity)}`}>查看识别结果<ChevronRight size={15} /></Link>
            </div>}
          </article>
        ))}</div>
      </div>}
      {matchTargets && <AddAnimeDialog allowLocal={false} bangumiActionLabel="匹配" bangumiActionIcon={Check} dialogTitle="匹配 Bangumi 动画" dialogDescription={`将 ${matchTargets.map((series) => `“${series.title}”`).join("、")} 固定到同一部 Bangumi 动画；匹配后不会自动开始追番。`} initialMode="bangumi" initialTitle={matchTargets[0]?.title ?? ""} onClose={() => setMatchTargets(null)} onSelected={async (animeRecord) => { await match.mutateAsync({ animeRecord, targets: matchTargets }); }} />}
    </section>
  );
}
