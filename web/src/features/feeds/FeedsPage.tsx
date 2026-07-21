import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCw, Rss, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { refreshFeed } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatInterval, formatRelative } from "../../shared/lib/format";
import { FeedFormDialog } from "./FeedFormDialog";
import { feedsQuery } from "./queries";

export function FeedsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const feeds = useQuery(feedsQuery);
  const refresh = useMutation({
    mutationFn: refreshFeed,
    onMutate: setRefreshingId,
    onSettled: async (_data, _error, feedId) => {
      setRefreshingId(null);
      await queryClient.invalidateQueries({ queryKey: ["feeds"] });
      await queryClient.invalidateQueries({ queryKey: ["releases"] });
      await queryClient.invalidateQueries({ queryKey: ["feeds", feedId] });
    },
  });

  return (
    <>
      <PageHeader eyebrow="来源管理" title="订阅源" description="管理 RSS 与 Atom 来源，检查连接状态和最近抓取结果。" actions={<Button variant="primary" icon={<Plus size={17} />} onClick={() => setDialogOpen(true)}>添加订阅源</Button>} />
      <div className="notice-strip"><ShieldCheck size={18} /><span>订阅地址和自定义请求头在数据库中加密保存，界面只展示脱敏地址。</span></div>
      {feeds.isLoading && <LoadingState label="正在读取订阅源" />}
      {feeds.isError && <ErrorBanner message="订阅源加载失败，请确认后端服务正在运行。" />}
      {refresh.isError && <ErrorBanner message="本次刷新失败，详情已记录到抓取历史。" />}

      {feeds.data?.length === 0 && <EmptyState icon={Rss} title="还没有订阅源" description="添加第一个 RSS 或 Atom 地址，测试连接后即可开始抓取。" action={<Button variant="primary" icon={<Plus size={17} />} onClick={() => setDialogOpen(true)}>添加订阅源</Button>} />}

      {feeds.data && feeds.data.length > 0 && (
        <div className="feed-list">
          {feeds.data.map((feed) => (
            <article className="feed-item" key={feed.id}>
              <div className="feed-item__main">
                <div className="feed-icon"><Rss size={20} /></div>
                <div className="feed-copy"><div className="feed-title-line"><h2>{feed.name}</h2><StatusBadge status={feed.health} /></div><p>{feed.url_redacted}</p></div>
              </div>
              <div className="feed-meta"><span><small>刷新频率</small>{formatInterval(feed.interval_seconds)}</span><span><small>上次成功</small>{formatRelative(feed.last_success_at)}</span><span><small>下次计划</small>{formatRelative(feed.next_fetch_at)}</span></div>
              <div className="feed-actions">
                <Button aria-label={`刷新 ${feed.name}`} title="立即刷新" size="icon" variant="ghost" disabled={refreshingId === feed.id} icon={<RefreshCw className={refreshingId === feed.id ? "spin" : ""} size={17} />} onClick={() => refresh.mutate(feed.id)} />
                <Link className="button button--secondary button--small" to={`/feeds/${feed.id}`}>查看详情<ArrowRight size={16} /></Link>
              </div>
            </article>
          ))}
        </div>
      )}
      <FeedFormDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </>
  );
}
