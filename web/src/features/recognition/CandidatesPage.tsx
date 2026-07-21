import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Layers3, PencilLine, Search, ShieldCheck, UsersRound, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import {
  confirmCandidate,
  listEpisodeGroups,
  listUnmatchedReleases,
  remapRelease,
  type Candidate,
  type ReleaseRemap,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

type CandidateTab = "grouped" | "unmatched";
type RemapTarget = {
  release_id: string;
  source_title: string;
  series_title?: string;
  episode_start?: string;
  episode_end?: string | null;
  season?: number | null;
  release_group?: string | null;
};

function mediaSummary(candidate: Candidate): string {
  return [candidate.resolution, candidate.video_codec, candidate.subtitle_language]
    .filter(Boolean)
    .join(" · ") || "媒体属性未知";
}

export function CandidatesPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<CandidateTab>("grouped");
  const [search, setSearch] = useState("");
  const [remapTarget, setRemapTarget] = useState<RemapTarget | null>(null);
  const groups = useQuery({ queryKey: ["episode-groups"], queryFn: listEpisodeGroups });
  const unmatched = useQuery({ queryKey: ["unmatched-releases"], queryFn: listUnmatchedReleases });
  const filteredGroups = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return groups.data ?? [];
    return (groups.data ?? []).filter((group) =>
      group.series_title.toLowerCase().includes(query)
      || group.episode_key.toLowerCase().includes(query)
      || group.candidates.some((candidate) => candidate.release_group?.toLowerCase().includes(query)),
    );
  }, [groups.data, search]);
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

  return (
    <>
      <PageHeader eyebrow="标题识别" title="剧集候选" description="按动画和集数查看不同字幕组的发布版本，保留每个候选的解析依据。" />
      {(groups.isLoading || unmatched.isLoading) && <LoadingState label="正在整理剧集候选" />}
      {(groups.isError || unmatched.isError || confirm.isError || remap.isError) && <ErrorBanner message="候选识别操作未完成，请检查输入后重试。" />}
      {groups.data && unmatched.data && (
        <>
          <section className="overview-band" aria-label="候选识别指标">
            <div className="overview-metric"><span className="metric-icon metric-icon--green"><Layers3 size={19} /></span><div><small>剧集组</small><strong>{groups.data.length}</strong></div></div>
            <div className="overview-metric"><span className="metric-icon metric-icon--blue"><UsersRound size={19} /></span><div><small>多版本剧集</small><strong>{duplicateGroups}</strong></div></div>
            <div className="overview-metric"><span className={`metric-icon ${unmatched.data.length ? "metric-icon--red" : "metric-icon--gray"}`}><AlertCircle size={19} /></span><div><small>待识别</small><strong>{unmatched.data.length}</strong></div></div>
          </section>

          <div className="candidate-toolbar">
            <div className="segmented" role="tablist" aria-label="候选识别状态">
              <button className={tab === "grouped" ? "segmented__active" : ""} role="tab" aria-selected={tab === "grouped"} onClick={() => setTab("grouped")}>已归组 <span>{groups.data.length}</span></button>
              <button className={tab === "unmatched" ? "segmented__active" : ""} role="tab" aria-selected={tab === "unmatched"} onClick={() => setTab("unmatched")}>待识别 <span>{unmatched.data.length}</span></button>
            </div>
            {tab === "grouped" && <label className="search-field candidate-search"><Search size={17} /><input aria-label="搜索剧集候选" placeholder="搜索动画、集数或字幕组" value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
          </div>

          {tab === "grouped" && filteredGroups.length === 0 && <EmptyState icon={Layers3} title={groups.data.length ? "没有匹配结果" : "还没有剧集候选"} description={groups.data.length ? "清空搜索条件或尝试其他关键词。" : "刷新包含可识别动画标题的订阅源后，候选会按集数归组。"} />}
          {tab === "grouped" && filteredGroups.length > 0 && <div className="episode-group-list">{filteredGroups.map((group) => (
            <article className="episode-group" key={group.key}>
              <header className="episode-group__header"><div><span className="episode-number">第 {group.episode_key} 集</span><h2>{group.series_title}</h2></div><span className="candidate-count">{group.candidate_count} 个候选</span></header>
              <div className="candidate-list">{group.candidates.map((candidate) => (
                <div className="candidate-row" key={candidate.id}>
                  <div className="candidate-group"><strong>{candidate.release_group ?? "未知字幕组"}</strong><small title={candidate.source_title}>{candidate.source_title}</small></div>
                  <span className="candidate-media">{mediaSummary(candidate)}</span>
                  <span className="revision-label">V{candidate.revision}</span>
                  <StatusBadge status={candidate.confidence} />
                  <span className={candidate.recognition_eligible ? "eligibility eligibility--yes" : "eligibility"}><CheckCircle2 size={16} />{candidate.recognition_eligible ? "可参与选择" : "需确认"}</span>
                  <div className="candidate-actions">
                    {!candidate.recognition_eligible && <Button aria-label="确认候选" title="确认候选" size="icon" variant="ghost" icon={<ShieldCheck size={16} />} disabled={confirm.isPending} onClick={() => confirm.mutate(candidate.id)} />}
                    <Button aria-label="修正映射" title="修正映射" size="icon" variant="ghost" icon={<PencilLine size={16} />} onClick={() => setRemapTarget(candidate)} />
                  </div>
                </div>
              ))}</div>
            </article>
          ))}</div>}

          {tab === "unmatched" && unmatched.data.length === 0 && <EmptyState icon={CheckCircle2} title="没有待识别条目" description="当前所有可用 Release 都已经获得动画和集数候选。" />}
          {tab === "unmatched" && unmatched.data.length > 0 && <div className="unmatched-list">{unmatched.data.map((release) => <article key={release.id}><div><strong>{release.source_title}</strong><small>{formatDate(release.parsed_at)}</small></div><span className="reason-code">{release.reason_code}</span><Button aria-label="人工映射" title="人工映射" size="icon" variant="ghost" icon={<PencilLine size={16} />} onClick={() => setRemapTarget(release)} /></article>)}</div>}
        </>
      )}
      {remapTarget && <RemapDialog release={remapTarget} pending={remap.isPending} onClose={() => setRemapTarget(null)} onSubmit={(payload) => remap.mutate({ releaseId: remapTarget.release_id, payload })} />}
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
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section aria-modal="true" className="dialog" role="dialog"><header className="dialog__header"><div><h2>人工映射发布条目</h2><p title={release.source_title}>{release.source_title}</p></div><Button aria-label="关闭" title="关闭" size="icon" variant="ghost" icon={<X size={18} />} onClick={onClose} /></header><form onSubmit={submit}><div className="form-stack"><label className="field"><span>动画标题</span><input required value={seriesTitle} onChange={(event) => setSeriesTitle(event.target.value)} /></label><div className="remap-fields"><label className="field"><span>季度</span><input type="number" min="0" max="99" value={season} onChange={(event) => setSeason(event.target.value)} /></label><label className="field"><span>起始集</span><input required value={episodeStart} placeholder="1" onChange={(event) => setEpisodeStart(event.target.value)} /></label><label className="field"><span>结束集</span><input value={episodeEnd} placeholder="可选" onChange={(event) => setEpisodeEnd(event.target.value)} /></label></div><label className="field"><span>字幕组</span><input value={releaseGroup} placeholder="可选" onChange={(event) => setReleaseGroup(event.target.value)} /></label></div><div className="dialog__actions"><Button type="button" variant="secondary" onClick={onClose}>取消</Button><Button type="submit" variant="primary" icon={<PencilLine size={16} />} disabled={pending}>{pending ? "映射中" : "保存映射"}</Button></div></form></section></div>;
}
