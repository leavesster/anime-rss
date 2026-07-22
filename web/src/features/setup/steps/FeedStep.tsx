import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Rss, TestTube2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  createFeed,
  listFeedEntries,
  listFeeds,
  refreshFeed,
  testFeed,
  type FeedEntry,
} from "../../../generated/api/client";
import { Button } from "../../../shared/components/Button";
import { ErrorBanner, LoadingState } from "../../../shared/components/Feedback";
import { StepFrame } from "../StepFrame";

function parseHeaders(value: string): Record<string, string> {
  return Object.fromEntries(value.split("\n").map((line) => {
    const separator = line.indexOf(":");
    return separator < 1 ? ["", ""] : [line.slice(0, separator).trim(), line.slice(separator + 1).trim()];
  }).filter(([name]) => name));
}

export function FeedStep({ onComplete }: { onComplete: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const feeds = useQuery({ queryKey: ["feeds"], queryFn: listFeeds });
  const existing = feeds.data?.[0];
  const entries = useQuery({
    queryKey: ["feeds", existing?.id, "entries"],
    queryFn: () => listFeedEntries(existing!.id),
    enabled: Boolean(existing),
  });
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [sourceType, setSourceType] = useState<"aggregate" | "single_anime">("aggregate");
  const [interval, setInterval] = useState(600);
  const [headers, setHeaders] = useState("");
  const [preview, setPreview] = useState<FeedEntry[]>([]);
  const add = useMutation({
    mutationFn: async () => {
      const payload = { name: name.trim(), url: url.trim(), source_type: sourceType, interval_seconds: interval, headers: parseHeaders(headers) };
      const tested = await testFeed(payload);
      if (tested.status !== "success") throw new Error(tested.error_code ?? "订阅源解析失败");
      const feed = await createFeed(payload);
      const refreshed = await refreshFeed(feed.id);
      if (refreshed.status !== "success") throw new Error(refreshed.error_code ?? "订阅源刷新失败");
      const normalized = await listFeedEntries(feed.id);
      setPreview(normalized);
      return feed;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["feeds"] });
    },
  });
  const finish = useMutation({ mutationFn: onComplete });
  const visibleEntries = preview.length ? preview : (entries.data ?? []);
  const hasFeed = Boolean(existing || add.data);
  const submit = (event: FormEvent) => { event.preventDefault(); add.mutate(); };

  return (
    <StepFrame icon={Rss} title="添加订阅源" summary="连接 RSS 或 Atom 并检查规范化条目">
      {(feeds.isError || entries.isError || add.isError || finish.isError) && <ErrorBanner message={(add.error ?? finish.error)?.message ?? "订阅源读取失败"} />}
      {feeds.isLoading && <LoadingState label="正在读取订阅源" />}
      {!feeds.isLoading && !hasFeed && <form className="setup-form" onSubmit={submit}>
        <div className="segmented" role="tablist" aria-label="订阅源类型">
          <button type="button" role="tab" aria-selected={sourceType === "single_anime"} className={sourceType === "single_anime" ? "segmented__active" : ""} onClick={() => setSourceType("single_anime")}>单一动画</button>
          <button type="button" role="tab" aria-selected={sourceType === "aggregate"} className={sourceType === "aggregate" ? "segmented__active" : ""} onClick={() => setSourceType("aggregate")}>聚合 RSS</button>
        </div>
        <div className="setup-form__columns">
          <label className="field"><span>{sourceType === "single_anime" ? "动画名称" : "订阅源名称"}</span><input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder={sourceType === "single_anime" ? "动画名称" : "动画订阅源"} /></label>
          <label className="field"><span>刷新频率</span><select value={interval} onChange={(event) => setInterval(Number(event.target.value))}><option value={300}>5 分钟</option><option value={600}>10 分钟</option><option value={1800}>30 分钟</option><option value={3600}>60 分钟</option></select></label>
        </div>
        <label className="field"><span>订阅地址</span><input required type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/rss.xml" /></label>
        <label className="field"><span>自定义请求头 <small>每行一个 Header: value</small></span><textarea rows={3} value={headers} onChange={(event) => setHeaders(event.target.value)} /></label>
        <div className="setup-form__actions"><Button type="submit" variant="primary" icon={<TestTube2 size={16} />} disabled={add.isPending}>{add.isPending ? "正在连接" : "添加并预览"}</Button></div>
      </form>}
      {hasFeed && <div className="setup-preview">
        <div className="setup-preview__heading"><CheckCircle2 size={17} /><strong>{existing?.name ?? add.data?.name}</strong><span>{visibleEntries.length} 个规范化条目</span></div>
        {entries.isLoading ? <LoadingState label="正在读取条目" /> : <div className="setup-preview__list">
          {visibleEntries.slice(0, 8).map((entry) => <article key={entry.id}><strong>{entry.title}</strong><small>{entry.identity_strength} · {entry.release_status}</small></article>)}
          {visibleEntries.length === 0 && <p className="inline-note">订阅源当前没有条目。</p>}
        </div>}
        <div className="setup-form__actions"><Button variant="primary" icon={<CheckCircle2 size={16} />} disabled={finish.isPending} onClick={() => finish.mutate()}>确认并继续</Button></div>
      </div>}
    </StepFrame>
  );
}
