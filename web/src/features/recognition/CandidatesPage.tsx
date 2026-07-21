import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Layers3, Search, UsersRound } from "lucide-react";
import { useMemo, useState } from "react";

import {
  listEpisodeGroups,
  listUnmatchedReleases,
  type Candidate,
} from "../../generated/api/client";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

type CandidateTab = "grouped" | "unmatched";

function mediaSummary(candidate: Candidate): string {
  return [candidate.resolution, candidate.video_codec, candidate.subtitle_language]
    .filter(Boolean)
    .join(" · ") || "媒体属性未知";
}

export function CandidatesPage() {
  const [tab, setTab] = useState<CandidateTab>("grouped");
  const [search, setSearch] = useState("");
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

  return (
    <>
      <PageHeader eyebrow="标题识别" title="剧集候选" description="按动画和集数查看不同字幕组的发布版本，保留每个候选的解析依据。" />
      {(groups.isLoading || unmatched.isLoading) && <LoadingState label="正在整理剧集候选" />}
      {(groups.isError || unmatched.isError) && <ErrorBanner message="候选识别结果加载失败。" />}
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
                </div>
              ))}</div>
            </article>
          ))}</div>}

          {tab === "unmatched" && unmatched.data.length === 0 && <EmptyState icon={CheckCircle2} title="没有待识别条目" description="当前所有可用 Release 都已经获得动画和集数候选。" />}
          {tab === "unmatched" && unmatched.data.length > 0 && <div className="unmatched-list">{unmatched.data.map((release) => <article key={release.id}><div><strong>{release.source_title}</strong><small>{formatDate(release.parsed_at)}</small></div><span className="reason-code">{release.reason_code}</span></article>)}</div>}
        </>
      )}
    </>
  );
}
