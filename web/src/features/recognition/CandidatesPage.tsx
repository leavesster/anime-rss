import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Layers3, PencilLine, RefreshCw, Rss, Search, ShieldCheck, Trash2, UsersRound, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import {
  confirmCandidate,
  dismissRelease,
  listAnime,
  listDecisions,
  listEpisodeGroups,
  listSelectionSlots,
  listSubscriptions,
  listUnmatchedReleases,
  previewBackfill,
  remapRelease,
  rerunRecognition,
  type Candidate,
  type BackfillPreview,
  type EpisodeGroup,
  type RecognitionRerun,
  type ReleaseRemap,
  type UnmatchedRelease,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { Dialog } from "../../shared/components/Dialog";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState, SuccessBanner } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

type CandidateTab = "grouped" | "unmatched";
type SeriesGroup = {
  identity: string;
  title: string;
  bangumiId: number | null;
  candidateCount: number;
  latestSeenAt: string;
  episodes: EpisodeGroup[];
};
type RemapTarget = {
  release_id: string;
  source_title: string;
  series_title?: string;
  episode_start?: string;
  episode_end?: string | null;
  season?: number | null;
  release_group?: string | null;
};
type SelectionEvidence = {
  tone: "selected" | "waiting" | "rejected" | "candidate";
  label: string;
};

const episodeKeyCollator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });

function mediaSummary(candidate: Candidate): string {
  return [candidate.resolution, candidate.video_codec, candidate.subtitle_language]
    .filter(Boolean)
    .join(" · ") || "媒体属性未知";
}

function rerunMessage(result: RecognitionRerun): string {
  if (result.candidate_adopted && result.previous_candidate_id) {
    return "已重新识别标题并更新结果；页面已按当前动画和集数重新整理。";
  }
  if (result.candidate_adopted) {
    return "已重新识别标题，并加入对应的动画和集数。";
  }
  if (result.candidate_id) {
    return result.confidence === "low"
      ? "新识别结果不够可靠，已保留原来的动画和集数。"
      : "识别结果没有变化，已保留本次识别依据。";
  }
  return "仍无法确定动画或集数，已保留本次识别依据。";
}

function recognitionReason(reasonCode: string): string {
  const labels: Record<string, string> = {
    episode_not_found: "未识别出集数",
    series_not_found: "未识别出动画",
    parsed_series_episode_without_group: "未识别出字幕组",
    parser_rerun_low_confidence: "重新识别结果不够可靠",
  };
  return labels[reasonCode] ?? "暂时无法确定动画或集数";
}

function comparisonLabel(field: string | null): string {
  const labels: Record<string, string> = {
    release_group: "字幕组优先级较低",
    subtitle: "字幕语言优先级较低",
    resolution: "分辨率优先级较低",
    codec: "编码优先级较低",
    revision: "修订版本较旧",
    first_seen_at: "发布时间较晚",
    release_identity: "发布顺序靠后",
  };
  return field ? labels[field] ?? "排序低于当前首选" : "排序低于当前首选";
}

function rejectionLabel(reason: string): string {
  const labels: Record<string, string> = {
    not_eligible: "识别结果不足以自动处理",
    confidence_not_high: "识别可信度不足",
    content_kind_allowed: "内容类型不在允许范围",
    release_group_allowed: "字幕组不在允许范围",
    subtitle_allowed: "字幕语言不在允许范围",
    resolution_allowed: "分辨率不在允许范围",
    codec_allowed: "编码不在允许范围",
    manually_rejected: "已被手动排除",
    partially_overlaps_acquired_episodes: "与已获取集数部分重叠",
    episodes_already_covered: "对应集数已经获取",
  };
  return labels[reason] ?? "不符合当前规则";
}

export function CandidatesPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const seriesFilter = searchParams.get("series");
  const [tab, setTab] = useState<CandidateTab>("grouped");
  const [search, setSearch] = useState("");
  const [remapTarget, setRemapTarget] = useState<RemapTarget | null>(null);
  const [dismissTarget, setDismissTarget] = useState<UnmatchedRelease | null>(null);
  const [rerunResult, setRerunResult] = useState<RecognitionRerun | null>(null);
  const groups = useQuery({ queryKey: ["episode-groups"], queryFn: listEpisodeGroups });
  const anime = useQuery({ queryKey: ["anime"], queryFn: listAnime });
  const unmatched = useQuery({ queryKey: ["unmatched-releases"], queryFn: listUnmatchedReleases });
  const subscriptions = useQuery({ queryKey: ["subscriptions"], queryFn: listSubscriptions });
  const slots = useQuery({ queryKey: ["selection-slots"], queryFn: () => listSelectionSlots() });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: () => listDecisions() });
  const activeSubscriptions = (subscriptions.data ?? []).filter((item) => item.state !== "archived");
  const previews = useQueries({
    queries: activeSubscriptions.map((subscription) => ({
      queryKey: ["candidate-rule-preview", subscription.id],
      queryFn: () => previewBackfill(subscription.id),
      staleTime: 60_000,
    })),
  });
  const selectionEvidence = useMemo(() => {
    const result = new Map<string, SelectionEvidence>();
    const slotsBySubscriptionEpisode = new Map(
      (slots.data ?? []).map((slot) => [`${slot.subscription_id}:${slot.episode_key}`, slot]),
    );
    const decisionsById = new Map((decisions.data ?? []).map((decision) => [decision.id, decision]));
    activeSubscriptions.forEach((subscription, index) => {
      const ruleSource = subscription.uses_global_rules ? "全局规则" : "单独规则";
      for (const episode of (previews[index]?.data ?? []) as BackfillPreview[]) {
        const slot = slotsBySubscriptionEpisode.get(`${subscription.id}:${episode.episode_key}`);
        for (const candidate of episode.candidates) {
          const selectedDecision = slot?.selected_decision_id ? decisionsById.get(slot.selected_decision_id) : undefined;
          if (selectedDecision?.candidate_id === candidate.candidate_id) {
            result.set(candidate.candidate_id, { tone: "selected", label: `已选择 · ${ruleSource}` });
          } else if (episode.selected_candidate_id === candidate.candidate_id) {
            const state = slot?.state === "waiting_fallback"
              ? "当前最佳，正在等待首选版本"
              : slot?.state === "needs_confirmation"
                ? "当前最佳，需要确认"
                : "按当前规则首选";
            result.set(candidate.candidate_id, { tone: slot?.state === "waiting_fallback" ? "waiting" : "selected", label: `${state} · ${ruleSource}` });
          } else if (candidate.rejection_reasons.length > 0) {
            result.set(candidate.candidate_id, { tone: "rejected", label: `已排除：${rejectionLabel(candidate.rejection_reasons[0])} · ${ruleSource}` });
          } else {
            result.set(candidate.candidate_id, { tone: "candidate", label: `${comparisonLabel(candidate.first_loss_field)} · ${ruleSource}` });
          }
        }
      }
    });
    return result;
  }, [activeSubscriptions, decisions.data, previews, slots.data]);
  const animeById = useMemo(() => new Map((anime.data ?? []).map((item) => [item.id, item])), [anime.data]);
  const filteredGroups = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (groups.data ?? []).filter((group) => {
      if (seriesFilter && group.series_identity !== seriesFilter) return false;
      const catalogTitle = group.anime_id ? animeById.get(group.anime_id)?.primary_title.toLowerCase() : undefined;
      return !query
        || catalogTitle?.includes(query)
        || group.series_title.toLowerCase().includes(query)
        || group.episode_key.toLowerCase().includes(query)
        || group.candidates.some((candidate) => candidate.release_group?.toLowerCase().includes(query));
    });
  }, [animeById, groups.data, search, seriesFilter]);
  const seriesGroups = useMemo(() => {
    const grouped = new Map<string, SeriesGroup>();
    for (const group of filteredGroups) {
      const catalogAnime = group.anime_id ? animeById.get(group.anime_id) : undefined;
      const existing = grouped.get(group.series_identity);
      if (existing) {
        existing.episodes.push(group);
        existing.candidateCount += group.candidate_count;
        if (group.latest_seen_at > existing.latestSeenAt) existing.latestSeenAt = group.latest_seen_at;
        continue;
      }
      grouped.set(group.series_identity, {
        identity: group.series_identity,
        title: catalogAnime?.primary_title ?? group.series_title,
        bangumiId: catalogAnime?.bangumi_id ?? null,
        candidateCount: group.candidate_count,
        latestSeenAt: group.latest_seen_at,
        episodes: [group],
      });
    }
    return [...grouped.values()]
      .map((series) => ({
        ...series,
        episodes: series.episodes.sort((left, right) => episodeKeyCollator.compare(right.episode_key, left.episode_key)),
      }))
      .sort((left, right) => right.latestSeenAt.localeCompare(left.latestSeenAt) || episodeKeyCollator.compare(left.title, right.title));
  }, [animeById, filteredGroups]);
  const filteredSeries = groups.data?.find((group) => group.series_identity === seriesFilter);
  const filteredSeriesTitle = (filteredSeries?.anime_id ? animeById.get(filteredSeries.anime_id)?.primary_title : undefined) ?? filteredSeries?.series_title;
  const duplicateGroups = groups.data?.filter((group) => group.candidate_count > 1).length ?? 0;
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["episode-groups"] }),
      queryClient.invalidateQueries({ queryKey: ["unmatched-releases"] }),
      queryClient.invalidateQueries({ queryKey: ["selection-slots"] }),
      queryClient.invalidateQueries({ queryKey: ["decisions"] }),
      queryClient.invalidateQueries({ queryKey: ["operations-overview"] }),
    ]);
  };
  const confirm = useMutation({ mutationFn: confirmCandidate, onSuccess: refresh });
  const remap = useMutation({
    mutationFn: ({ releaseId, payload }: { releaseId: string; payload: ReleaseRemap }) => remapRelease(releaseId, payload),
    onSuccess: async () => { setRemapTarget(null); await refresh(); },
  });
  const dismiss = useMutation({
    mutationFn: dismissRelease,
    onSuccess: async () => { setDismissTarget(null); await refresh(); },
  });
  const rerun = useMutation({
    mutationFn: rerunRecognition,
    onMutate: () => setRerunResult(null),
    onSuccess: async (result) => { setRerunResult(result); await refresh(); },
  });

  return (
    <>
      <PageHeader eyebrow="RSS 识别结果" title="版本识别" description="先解析集数，再关联动画；每一步的结果和不同发布版本都会保留。" />
      {(groups.isLoading || unmatched.isLoading) && <LoadingState label="正在整理版本识别结果" />}
      {(groups.isError || unmatched.isError || confirm.isError || remap.isError || dismiss.isError || rerun.isError) && <ErrorBanner message="识别操作未完成，请检查输入后重试。" />}
      {rerunResult && <SuccessBanner message={rerunMessage(rerunResult)} />}
      {groups.data && unmatched.data && (
        <>
          <section className="overview-band" aria-label="版本识别结果">
            <div className="overview-metric"><span className="metric-icon metric-icon--green"><Layers3 size={19} /></span><div><small>已解析集数</small><strong>{groups.data.length}</strong></div></div>
            <div className="overview-metric"><span className="metric-icon metric-icon--blue"><UsersRound size={19} /></span><div><small>多版本集数</small><strong>{duplicateGroups}</strong></div></div>
            <div className="overview-metric"><span className={`metric-icon ${unmatched.data.length ? "metric-icon--amber" : "metric-icon--gray"}`}><AlertCircle size={19} /></span><div><small>待解析条目</small><strong>{unmatched.data.length}</strong></div></div>
          </section>

          <div className="candidate-toolbar">
            <div className="segmented" role="tablist" aria-label="版本识别状态">
              <button className={tab === "grouped" ? "segmented__active" : ""} role="tab" aria-selected={tab === "grouped"} onClick={() => setTab("grouped")}>已解析集数 <span>{groups.data.length}</span></button>
              <button className={tab === "unmatched" ? "segmented__active" : ""} role="tab" aria-selected={tab === "unmatched"} onClick={() => setTab("unmatched")}>待解析 <span>{unmatched.data.length}</span></button>
            </div>
            {tab === "grouped" && <label className="search-field candidate-search"><Search size={17} /><input aria-label="搜索版本识别结果" placeholder="搜索动画、集数或字幕组" value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
          </div>

          {tab === "grouped" && seriesFilter && <div className="candidate-series-filter"><span>正在查看 <strong>{filteredSeriesTitle ?? seriesFilter}</strong> 的识别结果</span><Button size="small" variant="ghost" icon={<X size={15} />} onClick={() => { const next = new URLSearchParams(searchParams); next.delete("series"); setSearchParams(next, { replace: true }); }}>查看全部动画</Button></div>}

          {tab === "grouped" && filteredGroups.length === 0 && <EmptyState icon={Layers3} title={groups.data.length ? "没有匹配结果" : "还没有已解析的集数"} description={groups.data.length ? "清空搜索条件或尝试其他关键词。" : "刷新订阅源后，解析出集数的版本会集中显示。"} />}
          {tab === "grouped" && filteredGroups.length > 0 && <div className="series-group-list">{seriesGroups.map((series) => (
            <section className="series-group" key={series.identity}>
              <header className="series-group__header"><div><h2>{series.title}</h2><span>{series.episodes.length} 集 · {series.candidateCount} 个版本</span></div>{series.bangumiId && <a className="bgm-link" href={`https://bgm.tv/subject/${series.bangumiId}`} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" aria-label={`在 Bangumi 查看《${series.title}》`} title="在 Bangumi 查看">bgm.tv</a>}</header>
              <div className="episode-group-list">{series.episodes.map((group) => (
                <article className="episode-group" key={group.key}>
                  <header className="episode-group__header"><span className="episode-number">第 {group.episode_key} 集</span><span className="candidate-count">{group.candidate_count} 个版本</span></header>
                  <div className="candidate-list">{group.candidates.map((candidate) => (
                    <div className="candidate-row" key={candidate.id}>
                      <div className="candidate-group"><strong>{candidate.release_group ?? "未知字幕组"}</strong><small title={candidate.source_title}>{candidate.source_title}</small>{selectionEvidence.get(candidate.id) && <span className={`candidate-selection candidate-selection--${selectionEvidence.get(candidate.id)?.tone}`}>{selectionEvidence.get(candidate.id)?.label}</span>}</div>
                      <span className="candidate-media">{mediaSummary(candidate)}</span>
                      <span className="revision-label">V{candidate.revision}</span>
                      <StatusBadge status={candidate.confidence} />
                      <span className={candidate.anime_id && candidate.recognition_eligible ? "eligibility eligibility--yes" : "eligibility"}><CheckCircle2 size={16} />{candidate.anime_id ? `已关联动画 · ${candidate.recognition_eligible ? "可参与版本选择" : "需要确认"}` : candidate.catalog_match_status === "ambiguous" ? "集数已解析 · 动画关联有歧义" : "集数已解析 · 动画待关联"}</span>
                      <div className="candidate-actions">
                        {candidate.source_url && <a className="button button--ghost button--icon external-link" href={candidate.source_url} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" aria-label="打开 RSS 原始条目" title="打开 RSS 原始条目"><Rss size={16} /></a>}
                        {!candidate.recognition_eligible && <Button aria-label="确认识别结果" title="确认识别结果" size="icon" variant="ghost" icon={<ShieldCheck size={16} />} disabled={confirm.isPending} onClick={() => confirm.mutate(candidate.id)} />}
                        <Button aria-label="重新识别标题" title="重新识别标题" size="icon" variant="ghost" icon={<RefreshCw className={rerun.isPending && rerun.variables === candidate.release_id ? "spin" : ""} size={16} />} disabled={rerun.isPending} onClick={() => rerun.mutate(candidate.release_id)} />
                        <Button aria-label="调整动画与集数" title="调整动画与集数" size="icon" variant="ghost" icon={<PencilLine size={16} />} onClick={() => setRemapTarget(candidate)} />
                      </div>
                    </div>
                  ))}</div>
                </article>
              ))}</div>
            </section>
          ))}</div>}

          {tab === "unmatched" && unmatched.data.length === 0 && <EmptyState icon={CheckCircle2} title="没有待解析条目" description="当前 RSS 条目都已经解析出集数。" />}
          {tab === "unmatched" && unmatched.data.length > 0 && <div className="unmatched-list">{unmatched.data.map((release) => <article key={release.id}><div className="unmatched-copy"><strong>{release.source_title}</strong><small>{formatDate(release.parsed_at)}</small></div><span className="reason-code">{recognitionReason(release.reason_code)}</span><div className="candidate-actions">{release.source_url && <a className="button button--ghost button--icon external-link" href={release.source_url} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" aria-label="打开 RSS 原始条目" title="打开 RSS 原始条目"><Rss size={16} /></a>}<Button aria-label="重新识别标题" title="重新识别标题" size="icon" variant="ghost" icon={<RefreshCw className={rerun.isPending && rerun.variables === release.release_id ? "spin" : ""} size={16} />} disabled={rerun.isPending} onClick={() => rerun.mutate(release.release_id)} /><Button size="small" variant="secondary" icon={<PencilLine size={15} />} onClick={() => setRemapTarget(release)}>填写动画与集数</Button><Button size="small" variant="ghost" icon={<Trash2 size={15} />} onClick={() => setDismissTarget(release)}>忽略</Button></div></article>)}</div>}
        </>
      )}
      {remapTarget && <RemapDialog release={remapTarget} pending={remap.isPending} onClose={() => setRemapTarget(null)} onSubmit={(payload) => remap.mutate({ releaseId: remapTarget.release_id, payload })} />}
      <Dialog open={dismissTarget !== null} title="忽略待解析条目" description="条目将不再出现在“待解析”；RSS 原始条目和识别记录仍会保留。" onClose={() => setDismissTarget(null)}>
        <p className="confirm-copy" title={dismissTarget?.source_title}>{dismissTarget?.source_title}</p>
        <div className="dialog__actions"><Button variant="secondary" onClick={() => setDismissTarget(null)}>取消</Button><Button variant="danger" icon={<Trash2 size={16} />} disabled={dismiss.isPending} onClick={() => dismissTarget && dismiss.mutate(dismissTarget.release_id)}>{dismiss.isPending ? "处理中" : "确认忽略"}</Button></div>
      </Dialog>
    </>
  );
}

function RemapDialog({ release, pending, onClose, onSubmit }: { release: RemapTarget; pending: boolean; onClose: () => void; onSubmit: (payload: ReleaseRemap) => void }) {
  const [seriesTitle, setSeriesTitle] = useState(release.series_title ?? "");
  const [episodeStart, setEpisodeStart] = useState(release.episode_start ?? "");
  const [episodeEnd, setEpisodeEnd] = useState(release.episode_end ?? "");
  const [season, setSeason] = useState(release.season?.toString() ?? "");
  const [releaseGroup, setReleaseGroup] = useState(release.release_group ?? "");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({
      series_title: seriesTitle,
      episode_start: episodeStart,
      episode_end: episodeEnd || null,
      season: season ? Number(season) : null,
      release_group: releaseGroup || null,
    });
  };
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section aria-modal="true" className="dialog" role="dialog"><header className="dialog__header"><div><h2>调整动画与集数</h2><p title={release.source_title}>{release.source_title}</p></div><Button aria-label="关闭" title="关闭" size="icon" variant="ghost" icon={<X size={18} />} onClick={onClose} /></header><form onSubmit={submit}><div className="form-stack"><label className="field"><span>动画标题</span><input required value={seriesTitle} onChange={(event) => setSeriesTitle(event.target.value)} /></label><div className="remap-fields"><label className="field"><span>季度</span><input type="number" min="0" max="99" value={season} onChange={(event) => setSeason(event.target.value)} /></label><label className="field"><span>起始集</span><input required value={episodeStart} placeholder="1" onChange={(event) => setEpisodeStart(event.target.value)} /></label><label className="field"><span>结束集</span><input value={episodeEnd} placeholder="可选" onChange={(event) => setEpisodeEnd(event.target.value)} /></label></div><label className="field"><span>字幕组</span><input value={releaseGroup} placeholder="可选" onChange={(event) => setReleaseGroup(event.target.value)} /></label></div><div className="dialog__actions"><Button type="button" variant="secondary" onClick={onClose}>取消</Button><Button type="submit" variant="primary" icon={<PencilLine size={16} />} disabled={pending}>{pending ? "保存中" : "保存调整"}</Button></div></form></section></div>;
}
