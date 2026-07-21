import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { type FormEvent, useState } from "react";

import { type Anime, createSubscription } from "../../generated/api/client";
import { ErrorBanner } from "../../shared/components/Feedback";

interface Props {
  anime: Anime[];
  unavailableAnimeIds: Set<string>;
  onClose: () => void;
}

function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function CreateSubscriptionDialog({ anime, unavailableAnimeIds, onClose }: Props) {
  const available = anime.filter((item) => !unavailableAnimeIds.has(item.id));
  const [animeId, setAnimeId] = useState(available[0]?.id ?? "");
  const [groups, setGroups] = useState("");
  const [useGlobalRules, setUseGlobalRules] = useState(true);
  const [aliases, setAliases] = useState("");
  const [waitMinutes, setWaitMinutes] = useState(120);
  const [savePath, setSavePath] = useState("");
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => createSubscription({
      anime_id: animeId,
      aliases: splitList(aliases),
      save_path: savePath || null,
      use_global_rules: useGlobalRules,
      rules: useGlobalRules ? null : {
        preferred_groups: splitList(groups),
        fallback_wait_minutes: waitMinutes,
      },
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
      onClose();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="subscription-dialog-title">
        <header className="dialog__header">
          <div><h2 id="subscription-dialog-title">新建追番</h2><p>规则会在每次候选评估和最终决策中保存快照。</p></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </header>
        {create.isError && <ErrorBanner message={create.error.message} />}
        {available.length === 0 ? <p className="inline-note">当前动画都已经建立追番。</p> : <form className="form-stack" onSubmit={submit}>
          <label className="field"><span>动画</span><select required value={animeId} onChange={(event) => setAnimeId(event.target.value)}>{available.map((item) => <option value={item.id} key={item.id}>{item.primary_title}</option>)}</select></label>
          <label className="toggle-line"><input type="checkbox" checked={useGlobalRules} onChange={(event) => setUseGlobalRules(event.target.checked)} /><span><strong>继承全局版本偏好</strong><small>全局偏好更新后，此追番自动使用新规则。</small></span></label>
          {!useGlobalRules && <><label className="field"><span>字幕组偏好 <small>按顺序，逗号分隔</small></span><input value={groups} onChange={(event) => setGroups(event.target.value)} placeholder="Nix-Raws, LoliHouse" /></label><label className="field"><span>备选等待时间 <small>分钟</small></span><input type="number" min={0} max={10080} value={waitMinutes} onChange={(event) => setWaitMinutes(Number(event.target.value))} /></label></>}
          <label className="field"><span>附加匹配别名 <small>逗号分隔</small></span><input value={aliases} onChange={(event) => setAliases(event.target.value)} /></label>
          <label className="field"><span>保存目录 <small>可选</small></span><input value={savePath} onChange={(event) => setSavePath(event.target.value)} placeholder="/downloads/anime" /></label>
          <div className="dialog__actions"><button className="button button--secondary" type="button" onClick={onClose}>取消</button><button className="button button--primary" disabled={create.isPending}>开始追番</button></div>
        </form>}
      </section>
    </div>
  );
}
