import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Check, CircleSlash2, RotateCcw, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  listDecisions,
  listManualActions,
  listSelectionSlots,
  markEpisodeAcquired,
  previewBackfill,
  rejectCandidate,
  resetEpisode,
  selectCandidate,
  type Subscription,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

export function EpisodeControlDialog({ subscription, onClose }: { subscription: Subscription; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [episodeKey, setEpisodeKey] = useState("");
  const preview = useQuery({ queryKey: ["backfill-preview", subscription.id], queryFn: () => previewBackfill(subscription.id) });
  const slots = useQuery({ queryKey: ["selection-slots", subscription.id], queryFn: () => listSelectionSlots(subscription.id) });
  const decisions = useQuery({ queryKey: ["decisions", subscription.id], queryFn: () => listDecisions(subscription.id) });
  const actions = useQuery({ queryKey: ["manual-actions", subscription.id], queryFn: () => listManualActions(subscription.id) });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["backfill-preview", subscription.id] }),
      queryClient.invalidateQueries({ queryKey: ["selection-slots"] }),
      queryClient.invalidateQueries({ queryKey: ["decisions"] }),
      queryClient.invalidateQueries({ queryKey: ["manual-actions", subscription.id] }),
    ]);
  };
  const command = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: refresh,
  });
  const latestDecisions = new Map<string, NonNullable<typeof decisions.data>[number]>();
  for (const decision of decisions.data ?? []) {
    if (!latestDecisions.has(decision.episode_key)) {
      latestDecisions.set(decision.episode_key, decision);
    }
  }
  const slotByEpisode = new Map((slots.data ?? []).map((slot) => [slot.episode_key, slot]));
  const loading = preview.isLoading || slots.isLoading || decisions.isLoading || actions.isLoading;
  const failed = preview.isError || slots.isError || decisions.isError || actions.isError || command.isError;

  const markAcquired = (event: FormEvent) => {
    event.preventDefault();
    if (!episodeKey.trim()) return;
    command.mutate(() => markEpisodeAcquired(subscription.id, episodeKey.trim()));
    setEpisodeKey("");
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="dialog dialog--wide" role="dialog" aria-modal="true" aria-labelledby="episode-control-title">
        <header className="dialog__header"><div><h2 id="episode-control-title">{subscription.anime_title} · 剧集</h2><p>每次选择、替换、拒绝和重置都会保留历史。</p></div><Button size="icon" variant="ghost" icon={<X size={18} />} aria-label="关闭" onClick={onClose} /></header>
        {loading && <LoadingState label="正在汇总剧集候选" />}
        {failed && <ErrorBanner message={command.error?.message ?? "剧集数据加载失败。"} />}
        <form className="episode-acquired-form" onSubmit={markAcquired}>
          <label className="field"><span>外部已获取的集数</span><input required value={episodeKey} onChange={(event) => setEpisodeKey(event.target.value)} placeholder="例如 3 或 12.5" /></label>
          <Button type="submit" icon={<BadgeCheck size={16} />} disabled={command.isPending}>标记已获取</Button>
        </form>
        {!loading && preview.data?.length === 0 && <EmptyState icon={BadgeCheck} title="还没有候选" description="新发布匹配后会按集数出现在这里。" />}
        <div className="episode-control-list">
          {preview.data?.map((episode) => {
            const current = latestDecisions.get(episode.episode_key);
            const slot = slotByEpisode.get(episode.episode_key);
            return <section className="episode-control" key={episode.episode_key}>
              <header><div><strong>第 {episode.episode_key} 集</strong><small>{current ? `当前选择于 ${formatDate(current.created_at)}` : "尚未形成下载决定"}</small></div><StatusBadge status={slot?.state ?? "open"} />{current && <Button size="small" variant="ghost" icon={<RotateCcw size={14} />} onClick={() => command.mutate(() => resetEpisode(subscription.id, episode.episode_key))}>重置</Button>}</header>
              {slot?.confirmation_reason?.kind === "episode_coverage_overlap" && <p className="field-error">该范围覆盖第 {String(slot.confirmation_reason.covered_episode_keys)} 集，其中第 {String(slot.confirmation_reason.already_covered_episode_keys)} 集已获取。自动下载已暂停。</p>}
              <div className="episode-candidates">{episode.candidates.map((candidate) => {
                const selected = current?.candidate_id === candidate.candidate_id;
                const overlap = candidate.coverage_status === "partial";
                const fullyCovered = candidate.coverage_status === "full";
                return <article key={candidate.candidate_id}><div><strong>{candidate.release_group ?? "未知字幕组"}</strong><small title={candidate.source_title}>{candidate.source_title}</small><span>{candidate.preferred ? "满足全部首选" : candidate.first_loss_field ? `首个差异：${candidate.first_loss_field}` : "可接受备选"}</span>{overlap && <span className="field-error">覆盖第 {candidate.covered_episode_keys.join("、")} 集；第 {candidate.already_covered_episode_keys.join("、")} 集已获取</span>}{fullyCovered && <span className="field-error">覆盖集数均已获取，选择会再次下载</span>}{candidate.rejection_reasons.length > 0 && !overlap && !fullyCovered && <span className="field-error">{candidate.rejection_reasons.join(" · ")}</span>}</div><div className="episode-candidate-actions"><Button size="small" variant={selected ? "secondary" : "primary"} icon={<Check size={14} />} disabled={selected || command.isPending} onClick={() => command.mutate(() => selectCandidate(subscription.id, candidate.candidate_id, { replace_existing: Boolean(current), override_filters: !candidate.eligible }))}>{selected ? "已选择" : current ? "替换" : overlap || fullyCovered ? "确认重复并选择" : candidate.eligible ? "选择" : "强制选择"}</Button><Button size="icon" variant="ghost" title="拒绝候选" aria-label="拒绝候选" disabled={selected || command.isPending} icon={<CircleSlash2 size={15} />} onClick={() => command.mutate(() => rejectCandidate(subscription.id, candidate.candidate_id))} /></div></article>;
              })}</div>
            </section>;
          })}
        </div>
        {actions.data && actions.data.length > 0 && <section className="manual-action-log"><h3>人工操作</h3>{actions.data.slice(0, 8).map((action) => <div key={action.id}><strong>{action.episode_key}</strong><span>{action.action}</span><small>{formatDate(action.created_at)}</small></div>)}</section>}
      </section>
    </div>
  );
}
