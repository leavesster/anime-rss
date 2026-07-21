import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Clock3, FileText, Pencil, RefreshCw, Rss, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteFeed, refreshFeed } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { Dialog } from "../../shared/components/Dialog";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate, formatInterval, formatRelative } from "../../shared/lib/format";
import { EditFeedDialog } from "./EditFeedDialog";
import { feedEntriesQuery, feedFetchesQuery, feedsQuery } from "./queries";

type DetailTab = "entries" | "history";

export function FeedDetailPage() {
  const { feedId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<DetailTab>("entries");
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const feeds = useQuery(feedsQuery);
  const entries = useQuery({ ...feedEntriesQuery(feedId), enabled: Boolean(feedId) });
  const fetches = useQuery({ ...feedFetchesQuery(feedId), enabled: Boolean(feedId) });
  const feed = feeds.data?.find((item) => item.id === feedId);

  const refresh = useMutation({
    mutationFn: () => refreshFeed(feedId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["feeds"] }),
        queryClient.invalidateQueries({ queryKey: ["feeds", feedId] }),
        queryClient.invalidateQueries({ queryKey: ["releases"] }),
      ]);
    },
  });
  const remove = useMutation({
    mutationFn: (version: number) => deleteFeed(feedId, version),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["feeds"] });
      navigate("/feeds");
    },
  });

  if (feeds.isLoading) return <LoadingState label="正在读取订阅源" />;
  if (!feed) return <EmptyState icon={Rss} title="订阅源不存在" description="它可能已经被删除。" action={<Link className="button button--secondary button--regular" to="/feeds">返回订阅源</Link>} />;

  return (
    <>
      <Link className="back-link" to="/feeds"><ArrowLeft size={16} />返回订阅源</Link>
      <header className="detail-header">
        <div className="detail-header__title"><div className="feed-icon feed-icon--large"><Rss size={23} /></div><div><div className="feed-title-line"><h1>{feed.name}</h1><StatusBadge status={feed.health} /></div><p>{feed.url_redacted}</p></div></div>
        <div className="page-actions"><Button icon={<Pencil size={16} />} onClick={() => setEditOpen(true)}>编辑</Button><Button variant="primary" icon={<RefreshCw className={refresh.isPending ? "spin" : ""} size={16} />} disabled={refresh.isPending} onClick={() => refresh.mutate()}>{refresh.isPending ? "刷新中" : "立即刷新"}</Button><Button aria-label="删除订阅源" title="删除订阅源" size="icon" variant="ghost" icon={<Trash2 size={17} />} onClick={() => setDeleteOpen(true)} /></div>
      </header>
      {(refresh.isError || remove.isError) && <ErrorBanner message="操作失败，请稍后重试。" />}
      {refresh.data && <div className="success-banner">刷新完成：发现 {refresh.data.entry_count} 个条目，其中 {refresh.data.new_entry_count} 个为新条目。</div>}

      <section className="stat-band" aria-label="订阅源状态">
        <div><small>刷新频率</small><strong>{formatInterval(feed.interval_seconds)}</strong></div>
        <div><small>上次尝试</small><strong>{formatRelative(feed.last_attempt_at)}</strong></div>
        <div><small>上次成功</small><strong>{formatRelative(feed.last_success_at)}</strong></div>
        <div><small>连续失败</small><strong>{feed.consecutive_failures} 次</strong></div>
      </section>

      <div className="segmented" role="tablist" aria-label="订阅源详情">
        <button className={tab === "entries" ? "segmented__active" : ""} role="tab" aria-selected={tab === "entries"} onClick={() => setTab("entries")}><FileText size={16} />条目 <span>{entries.data?.length ?? 0}</span></button>
        <button className={tab === "history" ? "segmented__active" : ""} role="tab" aria-selected={tab === "history"} onClick={() => setTab("history")}><Clock3 size={16} />抓取历史 <span>{fetches.data?.length ?? 0}</span></button>
      </div>

      {tab === "entries" && <section className="data-section">
        <div className="section-heading"><div><h2>最近条目</h2><p>已规范化并进入发布识别流程的源条目。</p></div></div>
        {entries.isLoading && <LoadingState />}
        {entries.data?.length === 0 && <EmptyState icon={FileText} title="暂时没有条目" description="执行一次刷新后，新条目会显示在这里。" />}
        {entries.data && entries.data.length > 0 && <div className="data-table"><div className="data-table__head entry-grid"><span>标题</span><span>标识强度</span><span>解析状态</span><span>首次发现</span></div>{entries.data.map((entry) => <div className="data-table__row entry-grid" key={entry.id}><div><strong>{entry.title}</strong>{entry.link_redacted && <small>{entry.link_redacted}</small>}</div><StatusBadge status={entry.identity_strength} /><StatusBadge status={entry.release_status} /><span>{formatDate(entry.first_seen_at)}</span></div>)}</div>}
      </section>}

      {tab === "history" && <section className="data-section">
        <div className="section-heading"><div><h2>抓取历史</h2><p>每次请求的结果、响应状态和新增条目数。</p></div></div>
        {fetches.isLoading && <LoadingState />}
        {fetches.data?.length === 0 && <EmptyState icon={Clock3} title="暂无抓取记录" description="首次刷新后会记录请求结果。" />}
        {fetches.data && fetches.data.length > 0 && <div className="data-table"><div className="data-table__head history-grid"><span>时间</span><span>结果</span><span>HTTP</span><span>条目</span><span>新增</span></div>{fetches.data.map((fetch) => <div className="data-table__row history-grid" key={fetch.id}><span>{formatDate(fetch.started_at)}</span><StatusBadge status={fetch.status} /><span>{fetch.http_status ?? "-"}</span><span>{fetch.entry_count}</span><strong>+{fetch.new_entry_count}</strong></div>)}</div>}
      </section>}

      <EditFeedDialog feed={feed} open={editOpen} onClose={() => setEditOpen(false)} />
      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} title="删除订阅源" description="这会删除该订阅源及其抓取条目，已经识别的发布记录会保留。">
        <div className="confirm-copy">确定删除“{feed.name}”吗？此操作无法撤销。</div><div className="dialog__actions"><Button onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate(feed.version)}>{remove.isPending ? "删除中" : "确认删除"}</Button></div>
      </Dialog>
    </>
  );
}
