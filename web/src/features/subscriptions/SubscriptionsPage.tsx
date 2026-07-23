import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, BookOpen, CalendarClock, Check, ChevronDown, ChevronUp, Clock3, Copy, History, ListTree, Plus, Sparkles } from "lucide-react";
import { useState } from "react";

import {
  listAnime,
  listDecisions,
  listEpisodeGroups,
  listSelectionSlots,
  listSubscriptions,
  type Subscription,
  type Anime,
  updateSubscription,
} from "../../generated/api/client";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { copyText } from "../../shared/lib/clipboard";
import { formatDate } from "../../shared/lib/format";
import { AddAnimeDialog } from "./AddAnimeDialog";
import { BackfillDialog } from "./BackfillDialog";
import { CreateSubscriptionDialog } from "./CreateSubscriptionDialog";
import { DiscoveredSeriesSection } from "./DiscoveredSeriesSection";
import { EpisodeControlDialog } from "./EpisodeControlDialog";
import { GlobalPreferencesPanel } from "./GlobalPreferencesPanel";
import { LifecycleMenu } from "./LifecycleMenu";
import { SelectionLogicPanel } from "./SelectionLogicPanel";
import { ScheduleDialog } from "./ScheduleDialog";

const decisionLabels: Record<string, string> = {
  selected_preferred: "首选",
  selected_fallback: "等待结束后选择",
  selected_backfill: "补番",
  selected_upgrade: "版本升级",
  selected_manual: "手动选择",
  selected_manual_replacement: "手动替换",
};

export function SubscriptionsPage() {
  const queryClient = useQueryClient();
  const [showAnime, setShowAnime] = useState(false);
  const [showSubscription, setShowSubscription] = useState(false);
  const [backfill, setBackfill] = useState<Subscription | null>(null);
  const [episodeControl, setEpisodeControl] = useState<Subscription | null>(null);
  const [scheduleAnime, setScheduleAnime] = useState<Anime | null>(null);
  const [copiedSubscriptionId, setCopiedSubscriptionId] = useState<string | null>(null);
  const [subscriptionView, setSubscriptionView] = useState<"active" | "archived">("active");
  const [showRecentDecisions, setShowRecentDecisions] = useState(true);
  const anime = useQuery({ queryKey: ["anime"], queryFn: listAnime });
  const subscriptions = useQuery({ queryKey: ["subscriptions"], queryFn: listSubscriptions });
  const slots = useQuery({ queryKey: ["selection-slots"], queryFn: () => listSelectionSlots() });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: () => listDecisions() });
  const groups = useQuery({ queryKey: ["episode-groups"], queryFn: listEpisodeGroups });
  const lifecycle = useMutation({
    mutationFn: ({ subscription, state }: { subscription: Subscription; state: "following" | "paused" | "completed" | "archived" }) => updateSubscription(subscription.id, subscription.version, { state }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["subscriptions"] }); },
  });
  const loading = anime.isLoading || subscriptions.isLoading || slots.isLoading || decisions.isLoading || groups.isLoading;
  const failed = anime.isError || subscriptions.isError || slots.isError || decisions.isError || groups.isError;
  const waiting = slots.data?.filter((item) => item.state === "waiting_fallback").length ?? 0;
  const following = subscriptions.data?.filter((item) => item.state === "following").length ?? 0;
  const archived = subscriptions.data?.filter((item) => item.state === "archived").length ?? 0;
  const visibleSubscriptions = subscriptions.data?.filter((item) =>
    subscriptionView === "archived" ? item.state === "archived" : item.state !== "archived",
  ) ?? [];
  const copyAnimeTitle = async (subscription: Subscription) => {
    if (!await copyText(subscription.anime_title)) return;
    setCopiedSubscriptionId(subscription.id);
    window.setTimeout(() => setCopiedSubscriptionId(null), 1600);
  };

  return (
    <>
      <PageHeader eyebrow="版本选择" title="追番管理" description="添加动画并设置追番规则，查看等待中的剧集和每次版本选择。" actions={<><button className="button button--secondary" onClick={() => setShowAnime(true)}><BookOpen size={16} />添加动画</button><button className="button button--primary" onClick={() => setShowSubscription(true)} disabled={!anime.data?.length}><Plus size={16} />新建追番</button></>} />
      {loading && <LoadingState label="正在读取追番状态" />}
      {(failed || lifecycle.isError) && <ErrorBanner message={lifecycle.error?.message ?? "追番和版本选择状态加载失败。"} />}
      {anime.data && subscriptions.data && slots.data && decisions.data && groups.data && <>
        <section className="overview-band" aria-label="追番指标">
          <div className="overview-metric"><span className="metric-icon metric-icon--green"><BookOpen size={19} /></span><div><small>正在追番</small><strong>{following}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--blue"><Clock3 size={19} /></span><div><small>等待首选版本</small><strong>{waiting}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--gray"><Sparkles size={19} /></span><div><small>选择记录</small><strong>{decisions.data.length}</strong></div></div>
        </section>

        <div className="subscription-layout">
          <section className="data-section"><div className="section-heading"><div><h2>追番订阅</h2><p>完结仅接收同组修订版；归档停止全部自动处理。</p></div><div className="segmented" aria-label="订阅视图"><button className={subscriptionView === "active" ? "active" : ""} onClick={() => setSubscriptionView("active")}>当前</button><button className={subscriptionView === "archived" ? "active" : ""} onClick={() => setSubscriptionView("archived")}><Archive size={14} />归档 {archived}</button></div></div>
            {subscriptions.data.length === 0 ? <EmptyState icon={BookOpen} title="还没有追番" description="先添加动画，再设置字幕组偏好和等待首选版本的时间。" /> : visibleSubscriptions.length === 0 ? <EmptyState icon={Archive} title={subscriptionView === "archived" ? "没有归档订阅" : "没有当前订阅"} description={subscriptionView === "archived" ? "归档后的订阅会集中显示在这里。" : "恢复归档订阅或创建新的追番。"} /> : <div className="subscription-list">{visibleSubscriptions.map((subscription) => <article className="subscription-row" key={subscription.id}>
              <div className="subscription-row__main"><span className="subscription-mark"><BookOpen size={18} /></span><div><div className="subscription-title-line"><strong>{subscription.anime_title}</strong><button className="title-copy-button" aria-label={copiedSubscriptionId === subscription.id ? `已复制《${subscription.anime_title}》名称` : `复制《${subscription.anime_title}》名称`} title={copiedSubscriptionId === subscription.id ? "已复制" : "复制动画名称"} onClick={() => void copyAnimeTitle(subscription)}>{copiedSubscriptionId === subscription.id ? <Check size={14} /> : <Copy size={14} />}</button></div><small>{subscription.match_keys.length} 个可识别名称 · 本轮追番开始于 {formatDate(subscription.activation_at)}</small></div></div>
              <div className="subscription-rule"><small>{subscription.uses_global_rules ? "全局字幕组优先级" : "单独字幕组优先级"}</small><strong>{subscription.rules.preferred_groups?.join(" › ") || "不限制"}</strong></div>
              <div className="subscription-rule"><small>等待首选版本</small><strong>{subscription.rules.fallback_wait_minutes ?? 120} 分钟</strong></div>
              <StatusBadge status={subscription.state} />
              <div className="feed-actions">{anime.data.find((item) => item.id === subscription.anime_id)?.bangumi_id && <a className="bgm-link" href={`https://bgm.tv/subject/${anime.data.find((item) => item.id === subscription.anime_id)?.bangumi_id}`} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" aria-label={`在 Bangumi 查看《${subscription.anime_title}》`} title="在 Bangumi 查看">bgm.tv</a>}<button className="button button--ghost button--small" onClick={() => setEpisodeControl(subscription)}><ListTree size={15} />剧集</button><button className="button button--ghost button--small" onClick={() => setScheduleAnime(anime.data.find((item) => item.id === subscription.anime_id) ?? null)}><CalendarClock size={15} />播出</button><button className="button button--ghost button--small" onClick={() => setBackfill(subscription)}><History size={15} />补番</button><LifecycleMenu state={subscription.state as "following" | "paused" | "completed" | "archived"} disabled={lifecycle.isPending} onChange={(state) => lifecycle.mutate({ subscription, state })} /></div>
            </article>)}</div>}
          </section>

          <section className="data-section"><div className="section-heading section-heading--collapsible"><button className="section-heading-toggle" type="button" aria-expanded={showRecentDecisions} aria-controls="recent-decisions-content" onClick={() => setShowRecentDecisions((current) => !current)}><span><strong role="heading" aria-level={2}>最近选择 {showRecentDecisions ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</strong><small>保留每次选择的原因，以及当时的字幕组、画质和编码。</small></span></button></div>
            {showRecentDecisions && (decisions.data.length === 0 ? <div id="recent-decisions-content"><EmptyState icon={Sparkles} title="还没有选择" description="新候选命中订阅后会进入首选、等待或人工确认状态；开始追番前的剧集需要手动补番。" /></div> : <div className="decision-list" id="recent-decisions-content">{decisions.data.map((decision) => <article key={decision.id}>
              <span className="decision-kind">{decisionLabels[decision.kind] ?? decision.kind}</span>
              <div><strong>{decision.anime_title} · 第 {decision.episode_key} 集</strong><small>{String(decision.candidate_snapshot.release_group ?? "未知字幕组")} · {String(decision.candidate_snapshot.resolution ?? "分辨率未知")} · {formatDate(decision.created_at)}</small></div>
              <StatusBadge status="decided" />
            </article>)}</div>)}
          </section>
        </div>

        <GlobalPreferencesPanel />
        <SelectionLogicPanel />

        <DiscoveredSeriesSection anime={anime.data} subscriptions={subscriptions.data} groups={groups.data} />
      </>}
      {showAnime && <AddAnimeDialog onClose={() => setShowAnime(false)} />}
      {showSubscription && anime.data && subscriptions.data && <CreateSubscriptionDialog anime={anime.data} unavailableAnimeIds={new Set(subscriptions.data.map((item) => item.anime_id))} onClose={() => setShowSubscription(false)} />}
      {backfill && <BackfillDialog subscription={backfill} onClose={() => setBackfill(null)} />}
      {episodeControl && <EpisodeControlDialog subscription={episodeControl} onClose={() => setEpisodeControl(null)} />}
      {scheduleAnime && <ScheduleDialog anime={scheduleAnime} onClose={() => setScheduleAnime(null)} />}
    </>
  );
}
