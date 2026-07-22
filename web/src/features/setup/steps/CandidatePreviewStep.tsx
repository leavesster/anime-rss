import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Eye, RefreshCw } from "lucide-react";

import {
  listSubscriptions,
  previewBackfill,
} from "../../../generated/api/client";
import { Button } from "../../../shared/components/Button";
import { ErrorBanner, LoadingState } from "../../../shared/components/Feedback";
import { StepFrame } from "../StepFrame";

export function CandidatePreviewStep({ onComplete }: { onComplete: () => Promise<void> }) {
  const subscriptions = useQuery({ queryKey: ["subscriptions"], queryFn: listSubscriptions });
  const subscription = subscriptions.data?.[0];
  const preview = useMutation({
    mutationFn: () => {
      if (!subscription) throw new Error("没有可预览的追番");
      return previewBackfill(subscription.id);
    },
  });
  const finish = useMutation({ mutationFn: onComplete });
  const error = subscriptions.error ?? preview.error ?? finish.error;
  const candidateCount = preview.data?.reduce((sum, item) => sum + item.candidates.length, 0) ?? 0;
  return (
    <StepFrame icon={Eye} title="预览现有候选" summary="只读检查历史候选，不执行补番">
      {subscriptions.isLoading && <LoadingState label="正在读取追番" />}
      {error && <ErrorBanner message={error.message} />}
      {subscription && !preview.data && <div className="setup-preview setup-preview--empty">
        <strong>{subscription.anime_title}</strong>
        <Button variant="primary" icon={<RefreshCw size={16} />} disabled={preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? "正在生成" : "生成候选预览"}</Button>
      </div>}
      {preview.data && <div className="setup-preview">
        <div className="setup-preview__heading"><CheckCircle2 size={17} /><strong>{preview.data.length} 个剧集</strong><span>{candidateCount} 个候选</span></div>
        <div className="setup-preview__list">
          {preview.data.slice(0, 12).map((item) => {
            const selected = item.candidates.find((candidate) => candidate.candidate_id === item.selected_candidate_id);
            return <article key={item.episode_key}><strong>第 {item.episode_key} 集 · {selected?.release_group ?? "无合格候选"}</strong><small>{selected?.source_title ?? `${item.candidates.length} 个候选`}</small></article>;
          })}
          {preview.data.length === 0 && <p className="inline-note">当前没有已知候选，后续刷新订阅源时会继续识别。</p>}
        </div>
        <div className="setup-form__actions"><Button variant="primary" icon={<CheckCircle2 size={16} />} disabled={finish.isPending} onClick={() => finish.mutate()}>完成初始化</Button></div>
      </div>}
    </StepFrame>
  );
}
