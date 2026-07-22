import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Radio, Search } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  createSubscription,
  importBangumi,
  listSubscriptions,
  searchBangumi,
  type Anime,
} from "../../../generated/api/client";
import { Button } from "../../../shared/components/Button";
import { ErrorBanner, LoadingState } from "../../../shared/components/Feedback";
import { splitList } from "../lib";
import { StepFrame } from "../StepFrame";

export function SubscriptionStep({ onComplete }: { onComplete: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const subscriptions = useQuery({ queryKey: ["subscriptions"], queryFn: listSubscriptions });
  const [query, setQuery] = useState("");
  const [imported, setImported] = useState<Anime | null>(null);
  const [aliases, setAliases] = useState("");
  const search = useMutation({ mutationFn: () => searchBangumi(query) });
  const importAnime = useMutation({
    mutationFn: importBangumi,
    onSuccess: (anime) => setImported(anime),
  });
  const subscribe = useMutation({
    mutationFn: async () => {
      if (!imported) throw new Error("请先导入动画");
      await createSubscription({
        anime_id: imported.id,
        aliases: splitList(aliases),
        rules: null,
        use_global_rules: true,
        save_path: null,
      });
      await onComplete();
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    },
  });
  const continueExisting = useMutation({ mutationFn: onComplete });
  const existing = subscriptions.data?.[0];
  const error = subscriptions.error ?? search.error ?? importAnime.error ?? subscribe.error ?? continueExisting.error;

  return (
    <StepFrame icon={Radio} title="订阅第一部动画" summary="从 Bangumi 添加动画并设置追番规则">
      {subscriptions.isLoading && <LoadingState label="正在读取追番" />}
      {error && <ErrorBanner message={error.message} />}
      {existing ? <div className="setup-preview">
        <div className="setup-preview__heading"><CheckCircle2 size={17} /><strong>{existing.anime_title}</strong><span>已建立追番</span></div>
        <div className="setup-form__actions"><Button variant="primary" disabled={continueExisting.isPending} onClick={() => continueExisting.mutate()}>继续</Button></div>
      </div> : <div className="setup-form">
        <form className="search-field setup-search" onSubmit={(event: FormEvent) => { event.preventDefault(); search.mutate(); }}>
          <Search size={17} /><input required minLength={2} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索动画名称" /><Button size="small" variant="primary" disabled={search.isPending}>搜索</Button>
        </form>
        {search.data?.stale && <p className="inline-note">Bangumi 暂不可用，当前结果来自缓存。</p>}
        <div className="setup-catalog-results">
          {search.data?.items.map((item) => <article key={item.bangumi_id}>
            <div><strong>{item.name_cn ?? item.name}</strong><small>{item.name}{item.air_date ? ` · ${item.air_date}` : ""}</small></div>
            <Button size="small" icon={<Download size={15} />} disabled={importAnime.isPending} onClick={() => importAnime.mutate(item.bangumi_id)}>导入</Button>
          </article>)}
        </div>
        {imported && <form className="setup-imported" onSubmit={(event) => { event.preventDefault(); subscribe.mutate(); }}>
          <div className="setup-preview__heading"><CheckCircle2 size={17} /><strong>{imported.primary_title}</strong><span>已导入</span></div>
          <label className="field"><span>其他名称（别名）<small>逗号分隔</small></span><input value={aliases} onChange={(event) => setAliases(event.target.value)} /></label>
          <div className="setup-form__actions"><Button type="submit" variant="primary" icon={<Radio size={16} />} disabled={subscribe.isPending}>开始追番</Button></div>
        </form>}
      </div>}
    </StepFrame>
  );
}
