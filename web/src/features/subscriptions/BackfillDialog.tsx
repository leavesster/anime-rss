import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { commitBackfill, previewBackfill, type BackfillPreview, type Subscription } from "../../generated/api/client";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";

interface Props {
  subscription: Subscription;
  onClose: () => void;
}

function coverageMessage(candidate: BackfillPreview["candidates"][number]): string | null {
  if (candidate.coverage_status === "partial") {
    return `已获取第 ${candidate.already_covered_episode_keys.join("、")} 集，需在剧集控制中手动确认`;
  }
  if (candidate.coverage_status === "full") {
    return `覆盖的第 ${candidate.covered_episode_keys.join("、")} 集均已获取`;
  }
  return null;
}

export function BackfillDialog({ subscription, onClose }: Props) {
  const queryClient = useQueryClient();
  const preview = useQuery({ queryKey: ["backfill", subscription.id], queryFn: () => previewBackfill(subscription.id) });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (preview.data) setSelected(new Set(preview.data.filter((item) => item.selected_candidate_id).map((item) => item.episode_key)));
  }, [preview.data]);
  const commit = useMutation({
    mutationFn: () => commitBackfill(subscription.id, [...selected]),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["selection-slots"] }),
        queryClient.invalidateQueries({ queryKey: ["decisions"] }),
      ]);
      onClose();
    },
  });

  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog dialog--wide" role="dialog" aria-modal="true" aria-labelledby="backfill-dialog-title">
        <header className="dialog__header">
          <div><h2 id="backfill-dialog-title">补番</h2><p>{subscription.anime_title} · 按当前规则直接选择每集最佳版本，不等待首选版本。</p></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </header>
        {preview.isLoading && <LoadingState label="正在生成补番预览" />}
        {(preview.isError || commit.isError) && <ErrorBanner message={(preview.error ?? commit.error)?.message ?? "补番请求失败"} />}
        <div className="backfill-list">{preview.data?.map((item) => {
          const winner = item.candidates.find((candidate) => candidate.candidate_id === item.selected_candidate_id);
          const blockedCandidate = item.candidates.find((candidate) => candidate.coverage_status !== "none");
          const blockedMessage = blockedCandidate ? coverageMessage(blockedCandidate) : null;
          const checked = selected.has(item.episode_key);
          return <label key={item.episode_key} className={`backfill-row ${winner ? "" : "backfill-row--disabled"}`}>
            <input type="checkbox" disabled={!winner} checked={checked} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(item.episode_key); else next.delete(item.episode_key); return next; })} />
            <span className="episode-number">第 {item.episode_key} 集</span>
            <div><strong>{winner?.release_group ?? (blockedMessage ? "集数覆盖冲突" : "没有合格候选")}</strong><small>{winner?.source_title ?? blockedMessage ?? item.candidates.flatMap((candidate) => candidate.rejection_reasons).join(" · ")}</small></div>
            {winner && <span className="eligibility eligibility--yes"><CheckCircle2 size={15} />{winner.preferred ? "首选" : "当前最佳"}</span>}
          </label>;
        })}</div>
        <div className="dialog__actions"><button className="button button--secondary" type="button" onClick={onClose}>取消</button><button className="button button--primary" type="button" disabled={!selected.size || commit.isPending} onClick={() => commit.mutate()}>确认 {selected.size} 集</button></div>
      </section>
    </div>
  );
}
