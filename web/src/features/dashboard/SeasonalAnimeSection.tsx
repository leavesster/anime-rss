import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenCheck,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  EyeOff,
  ImageOff,
  RefreshCw,
  RotateCcw,
  Star,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  dismissSeasonalAnime,
  followSeasonalAnime,
  getSeasonalOverview,
  markSeasonalAnimeWatched,
  refreshSeasonalOverview,
  type SeasonalAnime,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { StatusBadge } from "../../shared/components/StatusBadge";

type SeasonalFilter = "all" | "undecided" | "following" | "watched" | "dismissed";

const PAGE_SIZE = 16;

function currentPeriod() {
  const now = new Date();
  return { year: now.getFullYear(), quarter: Math.floor(now.getMonth() / 3) + 1 };
}

function shiftPeriod(year: number, quarter: number, amount: number) {
  const value = year * 4 + quarter - 1 + amount;
  return { year: Math.floor(value / 4), quarter: (value % 4) + 1 };
}

function isFollowingStatus(status: string) {
  return ["following", "paused", "completed"].includes(status);
}

function displayTitle(item: SeasonalAnime) {
  return item.name_cn || item.name;
}

function dateLabel(value: string | null) {
  if (!value) return "日期待定";
  const [, month, day] = value.split("-");
  return `${Number(month)} 月 ${Number(day)} 日`;
}

export function SeasonalAnimeSection() {
  const queryClient = useQueryClient();
  const initial = useMemo(currentPeriod, []);
  const [period, setPeriod] = useState(initial);
  const [filter, setFilter] = useState<SeasonalFilter>("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const seasonal = useQuery({
    queryKey: ["seasonal", period.year, period.quarter],
    queryFn: () => getSeasonalOverview(period.year, period.quarter),
    staleTime: 5 * 60_000,
  });
  const refresh = useMutation({
    mutationFn: () => refreshSeasonalOverview(period.year, period.quarter),
    onSuccess: (data) => queryClient.setQueryData(
      ["seasonal", period.year, period.quarter],
      data,
    ),
  });
  const action = useMutation({
    mutationFn: ({ bangumiId, kind }: { bangumiId: number; kind: "follow" | "watched" | "dismiss" }) => {
      if (kind === "follow") return followSeasonalAnime(bangumiId);
      if (kind === "watched") return markSeasonalAnimeWatched(bangumiId);
      return dismissSeasonalAnime(bangumiId);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["seasonal"] }),
        queryClient.invalidateQueries({ queryKey: ["subscriptions"] }),
        queryClient.invalidateQueries({ queryKey: ["schedule-calendar"] }),
      ]);
    },
  });

  const items = seasonal.data?.items ?? [];
  const counts = {
    all: items.length,
    undecided: items.filter((item) => item.status === "undecided").length,
    following: items.filter((item) => isFollowingStatus(item.status)).length,
    watched: items.filter((item) => item.status === "watched").length,
    dismissed: items.filter((item) => item.status === "dismissed").length,
  };
  const filtered = items.filter((item) => {
    if (filter === "all") return true;
    if (filter === "following") return isFollowingStatus(item.status);
    return item.status === filter;
  });
  const visible = filtered.slice(0, visibleCount);

  function movePeriod(amount: number) {
    setPeriod((value) => shiftPeriod(value.year, value.quarter, amount));
    setFilter("all");
    setVisibleCount(PAGE_SIZE);
  }

  return (
    <section className="seasonal-section" aria-labelledby="seasonal-heading">
      <div className="seasonal-toolbar">
        <div className="period-switcher" aria-label="新番季度">
          <Button size="icon" variant="secondary" aria-label="上一季度" title="上一季度" icon={<ChevronLeft size={18} />} onClick={() => movePeriod(-1)} />
          <h2 id="seasonal-heading">{seasonal.data?.title ?? `${period.year} 年第 ${period.quarter} 季度`}</h2>
          <Button size="icon" variant="secondary" aria-label="下一季度" title="下一季度" icon={<ChevronRight size={18} />} onClick={() => movePeriod(1)} />
        </div>
        <Button size="icon" variant="ghost" aria-label="刷新本季新番" title="刷新本季新番" disabled={refresh.isPending || seasonal.isFetching} icon={<RefreshCw className={refresh.isPending ? "spin" : ""} size={17} />} onClick={() => refresh.mutate()} />
      </div>

      {seasonal.isLoading && <LoadingState label="正在读取本季新番" />}
      {(seasonal.isError || refresh.isError || action.isError) && <ErrorBanner message={action.error?.message ?? refresh.error?.message ?? seasonal.error?.message ?? "本季新番加载失败。"} />}
      {seasonal.data?.stale && <div className="notice-strip"><span>Bangumi 暂时不可用，当前显示上次同步的数据。</span></div>}

      {seasonal.data && (
        <>
          <div className="seasonal-filters segmented" aria-label="新番状态筛选">
            {([
              ["all", "全部"],
              ["undecided", "待决定"],
              ["following", "正在追"],
              ["watched", "已看完"],
              ["dismissed", "不追"],
            ] as const).map(([value, label]) => (
              <button key={value} className={filter === value ? "segmented__active" : ""} onClick={() => { setFilter(value); setVisibleCount(PAGE_SIZE); }}>
                {label} <span>{counts[value]}</span>
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <EmptyState icon={BookOpenCheck} title="这里还没有动画" description="切换其他状态或季度查看。" />
          ) : (
            <div className="seasonal-grid">
              {visible.map((item) => {
                const title = displayTitle(item);
                const pending = action.isPending && action.variables?.bangumiId === item.bangumi_id;
                return (
                  <article className="seasonal-card" key={item.bangumi_id}>
                    <a className="seasonal-cover" href={`https://bgm.tv/subject/${item.bangumi_id}`} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" aria-label={`在 Bangumi 查看《${title}》`}>
                      {item.cover_url ? <img src={item.cover_url} alt={`《${title}》封面`} loading="lazy" /> : <span><ImageOff size={24} /></span>}
                    </a>
                    <div className="seasonal-card__body">
                      <div className="seasonal-card__status">
                        <StatusBadge status={item.status} />
                        <div className="seasonal-card__facts">
                          {typeof item.rating_score === "number" && Number.isFinite(item.rating_score) && (
                            <span
                              className="seasonal-rating"
                              aria-label={`Bangumi ${item.rating_total} 人评分`}
                              title={`Bangumi ${item.rating_total} 人评分`}
                            >
                              <Star size={11} fill="currentColor" aria-hidden="true" />
                              {item.rating_score.toFixed(1)}
                            </span>
                          )}
                          <small>{item.platform ?? "动画"}</small>
                        </div>
                      </div>
                      <div className="seasonal-card__titles">
                        <h3 title={title}>{title}</h3>
                        {item.name_cn && item.name_cn !== item.name && <small title={item.name}>{item.name}</small>}
                      </div>
                      <p>{dateLabel(item.air_date)}{item.episode_count ? ` · ${item.episode_count} 集` : ""}</p>
                      <div className="seasonal-card__actions">
                        {item.status === "undecided" && <>
                          <Button size="small" variant="primary" disabled={pending} icon={<BookOpenCheck size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "follow" })}>追番</Button>
                          <Button size="small" variant="secondary" disabled={pending} icon={<CircleCheck size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "watched" })}>已看完</Button>
                          <Button size="small" variant="secondary" disabled={pending} icon={<EyeOff size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "dismiss" })}>不追</Button>
                        </>}
                        {isFollowingStatus(item.status) && <>
                          {item.status !== "following" && <Button size="small" variant="primary" disabled={pending} icon={<RotateCcw size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "follow" })}>重新追番</Button>}
                          <Button size="small" variant="secondary" disabled={pending} icon={<CircleCheck size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "watched" })}>已看完</Button>
                          <Button size="small" variant="secondary" disabled={pending} icon={<EyeOff size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "dismiss" })}>不追了</Button>
                        </>}
                        {["dismissed", "watched"].includes(item.status) && <>
                          <Button size="small" variant="primary" disabled={pending} icon={<RotateCcw size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "follow" })}>重新追番</Button>
                          {item.status === "dismissed" && <Button size="small" variant="secondary" disabled={pending} icon={<CircleCheck size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "watched" })}>已看完</Button>}
                          {item.status === "watched" && <Button size="small" variant="secondary" disabled={pending} icon={<EyeOff size={15} />} onClick={() => action.mutate({ bangumiId: item.bangumi_id, kind: "dismiss" })}>改为不追</Button>}
                        </>}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          {visibleCount < filtered.length && <div className="progressive-footer"><Button size="small" variant="secondary" onClick={() => setVisibleCount((value) => value + PAGE_SIZE)}>显示更多</Button></div>}
        </>
      )}
    </section>
  );
}
