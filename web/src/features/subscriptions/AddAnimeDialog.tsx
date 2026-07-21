import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Search, X } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  createLocalAnime,
  importBangumi,
  searchBangumi,
} from "../../generated/api/client";
import { ErrorBanner } from "../../shared/components/Feedback";

interface Props {
  onClose: () => void;
}

function splitAliases(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function AddAnimeDialog({ onClose }: Props) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"local" | "bangumi">("local");
  const [title, setTitle] = useState("");
  const [aliases, setAliases] = useState("");
  const [query, setQuery] = useState("");
  const create = useMutation({
    mutationFn: () => createLocalAnime(title, splitAliases(aliases)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["anime"] });
      onClose();
    },
  });
  const search = useMutation({ mutationFn: () => searchBangumi(query) });
  const imported = useMutation({
    mutationFn: importBangumi,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["anime"] });
      onClose();
    },
  });

  function submitLocal(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    search.mutate();
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="anime-dialog-title">
        <header className="dialog__header">
          <div><h2 id="anime-dialog-title">添加动画</h2><p>从 Bangumi 导入元数据，或建立完全本地的动画身份。</p></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </header>
        <div className="segmented" role="tablist" aria-label="动画来源">
          <button type="button" role="tab" aria-selected={mode === "local"} className={mode === "local" ? "segmented__active" : ""} onClick={() => setMode("local")}>本地创建</button>
          <button type="button" role="tab" aria-selected={mode === "bangumi"} className={mode === "bangumi" ? "segmented__active" : ""} onClick={() => setMode("bangumi")}>Bangumi</button>
        </div>

        {mode === "local" && <form className="form-stack" onSubmit={submitLocal}>
          {create.isError && <ErrorBanner message={create.error.message} />}
          <label className="field"><span>动画名称</span><input required maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
          <label className="field"><span>匹配别名 <small>逗号分隔</small></span><input value={aliases} onChange={(event) => setAliases(event.target.value)} placeholder="日文名, 罗马字名" /></label>
          <div className="dialog__actions"><button className="button button--secondary" type="button" onClick={onClose}>取消</button><button className="button button--primary" disabled={create.isPending}>创建动画</button></div>
        </form>}

        {mode === "bangumi" && <div className="form-stack">
          {(search.isError || imported.isError) && <ErrorBanner message={(search.error ?? imported.error)?.message ?? "Bangumi 请求失败"} />}
          <form className="search-field catalog-search" onSubmit={submitSearch}><Search size={17} /><input aria-label="搜索 Bangumi 动画" required minLength={2} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入动画名称" /><button className="button button--primary button--small" disabled={search.isPending}>搜索</button></form>
          {search.data?.stale && <p className="inline-note">Bangumi 当前不可用，正在显示本地缓存结果。</p>}
          <div className="catalog-results">{search.data?.items.map((item) => <article key={item.bangumi_id}>
            <div><strong>{item.name_cn ?? item.name}</strong><small>{item.name}{item.air_date ? ` · ${item.air_date}` : ""}</small></div>
            <button className="button button--secondary button--small" type="button" onClick={() => imported.mutate(item.bangumi_id)} disabled={imported.isPending}><Download size={15} />导入</button>
          </article>)}</div>
        </div>}
      </section>
    </div>
  );
}
