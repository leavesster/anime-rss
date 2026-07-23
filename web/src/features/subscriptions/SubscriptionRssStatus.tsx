import { AlertTriangle, Check, ExternalLink, Link2Off, Radio } from "lucide-react";

import type {
  Anime,
  AnimeRssMatch,
  Subscription,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";

export function SubscriptionRssStatus({
  anime,
  subscription,
  rssMatch,
  pendingCandidateId,
  onCorrect,
}: {
  anime: Anime[];
  subscription: Subscription;
  rssMatch: AnimeRssMatch | undefined;
  pendingCandidateId: string | null;
  onCorrect: (conflict: AnimeRssMatch["conflicts"][number]) => void;
}) {
  const conflicts = rssMatch?.conflicts ?? [];
  const hasMatches = (rssMatch?.candidate_count ?? 0) > 0;
  const currentTitle = (animeId: string) =>
    anime.find((item) => item.id === animeId)?.primary_title ?? "另一部动画";

  return <>
    <div className={`subscription-rss subscription-rss--${conflicts.length > 0 ? "warning" : hasMatches ? "matched" : "empty"}`}>
      {conflicts.length > 0 ? <AlertTriangle size={16} /> : hasMatches ? <Radio size={16} /> : <Link2Off size={16} />}
      <span>
        <small>{conflicts.length > 0 ? "RSS 绑定需确认" : hasMatches ? "RSS 已匹配" : "RSS 未匹配"}</small>
        <strong>{conflicts.length > 0
          ? `${conflicts.length} 个疑似错误`
          : hasMatches
            ? `${rssMatch?.episode_count ?? 0} 集 · ${rssMatch?.candidate_count ?? 0} 个种子`
            : "尚无单集种子"}</strong>
      </span>
    </div>
    {conflicts.length > 0 && <div className="subscription-binding-warning" role="alert">
      <header><AlertTriangle size={17} /><div><strong>可能绑定到了错误的动画</strong><small>RSS 标题中的季数与当前绑定目标冲突，请逐项确认。</small></div></header>
      <div className="subscription-binding-conflicts">{conflicts.map((conflict) => (
        <article key={conflict.candidate_id}>
          <div>
            <strong>第 {conflict.episode_key} 集 · 目前绑定到《{currentTitle(conflict.current_anime_id)}》</strong>
            <small>{conflict.source_title}</small>
            <span>冲突依据：{conflict.evidence_titles.join(" / ")}</span>
          </div>
          <div className="subscription-binding-actions">
            {conflict.source_url && <a className="button button--ghost button--icon" href={conflict.source_url} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" aria-label="打开种子来源" title="打开种子来源"><ExternalLink size={16} /></a>}
            <Button aria-label={`将“${conflict.source_title}”改绑到《${subscription.anime_title}》`} size="small" variant="secondary" icon={pendingCandidateId === conflict.candidate_id ? undefined : <Check size={15} />} disabled={pendingCandidateId !== null} onClick={() => onCorrect(conflict)}>{pendingCandidateId === conflict.candidate_id ? "纠正中" : "纠正绑定"}</Button>
          </div>
        </article>
      ))}</div>
    </div>}
  </>;
}
