import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Clock3, History, ListTree, Pause, Play, Plus, Sparkles } from "lucide-react";
import { useState } from "react";

import {
  listAnime,
  listDecisions,
  listSelectionSlots,
  listSubscriptions,
  type Subscription,
  updateSubscription,
} from "../../generated/api/client";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";
import { AddAnimeDialog } from "./AddAnimeDialog";
import { BackfillDialog } from "./BackfillDialog";
import { CreateSubscriptionDialog } from "./CreateSubscriptionDialog";
import { EpisodeControlDialog } from "./EpisodeControlDialog";
import { GlobalPreferencesPanel } from "./GlobalPreferencesPanel";
import { SelectionLogicPanel } from "./SelectionLogicPanel";

const decisionLabels: Record<string, string> = {
  selected_preferred: "首选",
  selected_fallback: "备选到期",
  selected_backfill: "历史回填",
  selected_upgrade: "版本升级",
  selected_manual: "人工选择",
  selected_manual_replacement: "人工替换",
};

export function SubscriptionsPage() {
  const queryClient = useQueryClient();
  const [showAnime, setShowAnime] = useState(false);
  const [showSubscription, setShowSubscription] = useState(false);
  const [backfill, setBackfill] = useState<Subscription | null>(null);
  const [episodeControl, setEpisodeControl] = useState<Subscription | null>(null);
  const anime = useQuery({ queryKey: ["anime"], queryFn: listAnime });
  const subscriptions = useQuery({ queryKey: ["subscriptions"], queryFn: listSubscriptions });
  const slots = useQuery({ queryKey: ["selection-slots"], queryFn: () => listSelectionSlots() });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: () => listDecisions() });
  const lifecycle = useMutation({
    mutationFn: ({ subscription, state }: { subscription: Subscription; state: "following" | "paused" }) => updateSubscription(subscription.id, subscription.version, { state }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["subscriptions"] }); },
  });
  const loading = anime.isLoading || subscriptions.isLoading || slots.isLoading || decisions.isLoading;
  const failed = anime.isError || subscriptions.isError || slots.isError || decisions.isError;
  const waiting = slots.data?.filter((item) => item.state === "waiting_fallback").length ?? 0;
  const following = subscriptions.data?.filter((item) => item.state === "following").length ?? 0;

  return (
    <>
      <PageHeader eyebrow="订阅决策" title="追番管理" description="维护动画身份与订阅规则，查看等待窗口和每一次不可变选择。" actions={<><button className="button button--secondary" onClick={() => setShowAnime(true)}><BookOpen size={16} />添加动画</button><button className="button button--primary" onClick={() => setShowSubscription(true)} disabled={!anime.data?.length}><Plus size={16} />新建追番</button></>} />
      {loading && <LoadingState label="正在读取追番状态" />}
      {failed && <ErrorBanner message="追番和决策状态加载失败。" />}
      {anime.data && subscriptions.data && slots.data && decisions.data && <>
        <section className="overview-band" aria-label="追番指标">
          <div className="overview-metric"><span className="metric-icon metric-icon--green"><BookOpen size={19} /></span><div><small>正在追番</small><strong>{following}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--blue"><Clock3 size={19} /></span><div><small>等待备选</small><strong>{waiting}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--gray"><Sparkles size={19} /></span><div><small>已形成决策</small><strong>{decisions.data.length}</strong></div></div>
        </section>

        <GlobalPreferencesPanel />
        <SelectionLogicPanel />

        <div className="subscription-layout">
          <section className="data-section"><div className="section-heading"><div><h2>追番订阅</h2><p>暂停或恢复会切换激活时间边界。</p></div></div>
            {subscriptions.data.length === 0 ? <EmptyState icon={BookOpen} title="还没有追番" description="先添加动画身份，再为它配置字幕组偏好和备选等待时间。" /> : <div className="subscription-list">{subscriptions.data.map((subscription) => <article className="subscription-row" key={subscription.id}>
              <div className="subscription-row__main"><span className="subscription-mark"><BookOpen size={18} /></span><div><strong>{subscription.anime_title}</strong><small>{subscription.match_keys.length} 个匹配标题 · 激活于 {formatDate(subscription.activation_at)}</small></div></div>
              <div className="subscription-rule"><small>{subscription.uses_global_rules ? "全局字幕组优先级" : "单独字幕组优先级"}</small><strong>{subscription.rules.preferred_groups?.join(" › ") || "不限制"}</strong></div>
              <div className="subscription-rule"><small>备选等待</small><strong>{subscription.rules.fallback_wait_minutes ?? 120} 分钟</strong></div>
              <StatusBadge status={subscription.state} />
              <div className="feed-actions"><button className="button button--ghost button--small" onClick={() => setEpisodeControl(subscription)}><ListTree size={15} />剧集</button><button className="button button--ghost button--small" onClick={() => setBackfill(subscription)}><History size={15} />回填</button><button className="icon-button" aria-label={subscription.state === "following" ? "暂停追番" : "恢复追番"} onClick={() => lifecycle.mutate({ subscription, state: subscription.state === "following" ? "paused" : "following" })}>{subscription.state === "following" ? <Pause size={16} /> : <Play size={16} />}</button></div>
            </article>)}</div>}
          </section>

          <section className="data-section"><div className="section-heading"><div><h2>最近决策</h2><p>选择理由和当时的候选属性不会被后续配置覆盖。</p></div></div>
            {decisions.data.length === 0 ? <EmptyState icon={Sparkles} title="还没有选择" description="新候选命中订阅后会进入首选、等待或人工确认状态；历史条目使用回填。" /> : <div className="decision-list">{decisions.data.map((decision) => <article key={decision.id}>
              <span className="decision-kind">{decisionLabels[decision.kind] ?? decision.kind}</span>
              <div><strong>{decision.anime_title} · 第 {decision.episode_key} 集</strong><small>{String(decision.candidate_snapshot.release_group ?? "未知字幕组")} · {String(decision.candidate_snapshot.resolution ?? "分辨率未知")} · {formatDate(decision.created_at)}</small></div>
              <StatusBadge status="decided" />
            </article>)}</div>}
          </section>
        </div>
      </>}
      {showAnime && <AddAnimeDialog onClose={() => setShowAnime(false)} />}
      {showSubscription && anime.data && subscriptions.data && <CreateSubscriptionDialog anime={anime.data} unavailableAnimeIds={new Set(subscriptions.data.map((item) => item.anime_id))} onClose={() => setShowSubscription(false)} />}
      {backfill && <BackfillDialog subscription={backfill} onClose={() => setBackfill(null)} />}
      {episodeControl && <EpisodeControlDialog subscription={episodeControl} onClose={() => setEpisodeControl(null)} />}
    </>
  );
}
