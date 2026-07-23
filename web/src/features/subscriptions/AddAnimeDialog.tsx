import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Import, Search, X, type LucideIcon } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  createLocalAnime,
  importBangumi,
  searchBangumi,
  type Anime,
} from "../../generated/api/client";
import { ErrorBanner } from "../../shared/components/Feedback";

interface Props {
  onClose: () => void;
  onSelected?: (anime: Anime) => Promise<void> | void;
  initialTitle?: string;
  initialMode?: "local" | "bangumi";
  allowLocal?: boolean;
  dialogTitle?: string;
  dialogDescription?: string;
  bangumiActionLabel?: string;
  bangumiActionIcon?: LucideIcon;
  recommendFirstResult?: boolean;
}

function splitAliases(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function AddAnimeDialog({
  onClose,
  onSelected,
  initialTitle = "",
  initialMode = "local",
  allowLocal = true,
  dialogTitle = "添加动画",
  dialogDescription = "从 Bangumi 导入动画资料，或直接添加一部本地动画。",
  bangumiActionLabel = "导入",
  bangumiActionIcon: BangumiActionIcon = Import,
  recommendFirstResult = false,
}: Props) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"local" | "bangumi">(allowLocal ? initialMode : "bangumi");
  const [title, setTitle] = useState(initialTitle);
  const [aliases, setAliases] = useState("");
  const [query, setQuery] = useState(initialTitle);
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(() => {
    const value = initialTitle.trim();
    return recommendFirstResult && value.length >= 2 ? value : null;
  });
  const create = useMutation({
    mutationFn: async () => {
      const anime = await createLocalAnime(title, splitAliases(aliases));
      await onSelected?.(anime);
      return anime;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["anime"] }),
        queryClient.invalidateQueries({ queryKey: ["episode-groups"] }),
      ]);
      onClose();
    },
  });
  const search = useQuery({
    queryKey: ["bangumi-search", submittedQuery],
    queryFn: () => searchBangumi(submittedQuery ?? ""),
    enabled: submittedQuery !== null,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  const imported = useMutation({
    mutationFn: async (bangumiId: number) => {
      const anime = await importBangumi(bangumiId);
      await onSelected?.(anime);
      return anime;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["anime"] }),
        queryClient.invalidateQueries({ queryKey: ["episode-groups"] }),
      ]);
      onClose();
    },
  });

  function submitLocal(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (value === submittedQuery) {
      void search.refetch();
      return;
    }
    setSubmittedQuery(value);
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="anime-dialog-title">
        <header className="dialog__header">
          <div><h2 id="anime-dialog-title">{dialogTitle}</h2><p>{dialogDescription}</p></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </header>
        {allowLocal && <div className="segmented" role="tablist" aria-label="动画来源">
          <button type="button" role="tab" aria-selected={mode === "local"} className={mode === "local" ? "segmented__active" : ""} onClick={() => setMode("local")}>本地创建</button>
          <button type="button" role="tab" aria-selected={mode === "bangumi"} className={mode === "bangumi" ? "segmented__active" : ""} onClick={() => setMode("bangumi")}>Bangumi</button>
        </div>}

        {mode === "local" && <form className="form-stack" onSubmit={submitLocal}>
          {create.isError && <ErrorBanner message={create.error.message} />}
          <label className="field"><span>动画名称</span><input required maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
          <label className="field"><span>其他名称（别名）<small>逗号分隔</small></span><input value={aliases} onChange={(event) => setAliases(event.target.value)} placeholder="日文名, 罗马字名" /></label>
          <div className="dialog__actions"><button className="button button--secondary" type="button" onClick={onClose}>取消</button><button className="button button--primary" disabled={create.isPending}>创建动画</button></div>
        </form>}

        {mode === "bangumi" && <div className="form-stack">
          {(search.isError || imported.isError) && <ErrorBanner message={(search.error ?? imported.error)?.message ?? "Bangumi 请求失败"} />}
          <form className="search-field catalog-search" onSubmit={submitSearch}><Search size={17} /><input aria-label="搜索 Bangumi 动画" required minLength={2} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入动画名称" /><button className="button button--primary button--small" disabled={search.isFetching}>搜索</button></form>
          {search.data?.stale && <p className="inline-note">Bangumi 当前不可用，正在显示本地缓存结果。</p>}
          {search.isFetching && !search.data && <p className="inline-note">正在查找 Bangumi 推荐...</p>}
          {search.data?.items.length === 0 && <p className="inline-note">未找到可推荐动画，请调整关键词。</p>}
          <div className="catalog-results">{search.data?.items.map((item, index) => {
            const recommended = recommendFirstResult && index === 0;
            return <article className={recommended ? "catalog-result--recommended" : undefined} key={item.bangumi_id}>
              <div><strong>{item.name_cn ?? item.name}</strong><small>{item.name}{item.air_date ? ` · ${item.air_date}` : ""}</small><span className="catalog-result-id">{recommended ? "推荐 · " : ""}Bangumi ID {item.bangumi_id}</span></div>
              <button className={`button ${recommended ? "button--primary" : "button--secondary"} button--small`} type="button" onClick={() => imported.mutate(item.bangumi_id)} disabled={imported.isPending}><BangumiActionIcon size={15} />{recommended ? `${bangumiActionLabel}推荐` : bangumiActionLabel}</button>
            </article>;
          })}</div>
        </div>}
      </section>
    </div>
  );
}
