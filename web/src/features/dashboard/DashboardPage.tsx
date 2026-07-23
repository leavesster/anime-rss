import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Database,
  Plus,
  RefreshCw,
  Rss,
  ServerCog,
} from "lucide-react";
import { Link } from "react-router-dom";

import { getOperationsOverview, getScheduleOverview, listReleases, refreshSchedule } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState, SuccessBanner } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatRelative, truncateHash } from "../../shared/lib/format";
import { feedsQuery } from "../feeds/queries";

export function DashboardPage() {
  const queryClient = useQueryClient();
  const feeds = useQuery(feedsQuery);
  const releases = useQuery({ queryKey: ["releases"], queryFn: listReleases });
  const operations = useQuery({ queryKey: ["operations-overview"], queryFn: getOperationsOverview, refetchInterval: 15_000 });
  const schedule = useQuery({ queryKey: ["schedule-calendar"], queryFn: getScheduleOverview, staleTime: 5 * 60_000 });
  const scheduleSync = useMutation({
    mutationFn: refreshSchedule,
    onSuccess: (data) => queryClient.setQueryData(["schedule-calendar"], data),
  });
  const isLoading = feeds.isLoading || releases.isLoading || operations.isLoading || schedule.isLoading;
  const hasError = feeds.isError || releases.isError || operations.isError || schedule.isError;
  const healthyFeeds = feeds.data?.filter((feed) => feed.health === "healthy").length ?? 0;
  const attentionFeeds = feeds.data?.filter((feed) => !["healthy", "never_fetched"].includes(feed.health)) ?? [];

  return (
    <>
      <PageHeader eyebrow="运行概览" title="今天的追番状态" description="从异常开始处理，正常运行的订阅源保持安静。" actions={<Link className="button button--primary button--regular" to="/feeds"><Plus size={17} />添加订阅源</Link>} />
      {isLoading && <LoadingState label="正在汇总运行状态" />}
      {hasError && <ErrorBanner message="部分运行数据暂时无法加载。" />}
      {!isLoading && !hasError && (
        <>
          <section className="overview-band overview-band--four" aria-label="运行指标">
            <div className="overview-metric"><span className="metric-icon metric-icon--green"><CheckCircle2 size={19} /></span><div><small>健康订阅源</small><strong>{healthyFeeds}<span> / {feeds.data?.length ?? 0}</span></strong></div></div>
            <div className="overview-metric"><span className="metric-icon metric-icon--blue"><Database size={19} /></span><div><small>唯一发布</small><strong>{releases.data?.length ?? 0}</strong></div></div>
            <div className="overview-metric"><span className={`metric-icon ${(operations.data?.failed_work.length ?? 0) + (schedule.data?.missing.length ?? 0) ? "metric-icon--red" : "metric-icon--gray"}`}><AlertTriangle size={19} /></span><div><small>需要处理</small><strong>{(operations.data?.failed_work.length ?? attentionFeeds.length) + (schedule.data?.missing.length ?? 0)}</strong></div></div>
            <div className="overview-metric"><span className="metric-icon metric-icon--gray"><ServerCog size={19} /></span><div><small>后台调度</small><strong>{operations.data?.scheduler?.state ?? "启动中"}</strong></div></div>
          </section>

          {schedule.data && (
            <section className="dashboard-section schedule-section">
              <div className="section-heading">
                <div><h2>播出日历</h2><p>今天起八天，时间按实例时区显示</p></div>
                <Button size="small" variant="ghost" icon={<RefreshCw className={scheduleSync.isPending ? "spin" : ""} size={16} />} disabled={scheduleSync.isPending || schedule.isFetching} onClick={() => scheduleSync.mutate()}>{scheduleSync.isPending ? "同步中" : "同步播出信息"}</Button>
              </div>
              {scheduleSync.isError && <ErrorBanner message="播出信息同步失败，现有日历仍可查看。" />}
              {scheduleSync.isSuccess && <SuccessBanner message="播出信息已同步，日历已经更新。" />}
              <div className="schedule-calendar">
                {schedule.data.calendar.map((day) => (
                  <div className="schedule-day" key={day.date}>
                    <div className="schedule-day__header">
                      <strong>{new Intl.DateTimeFormat("zh-CN", { weekday: "short" }).format(new Date(`${day.date}T12:00:00`))}</strong>
                      <span>{day.date.slice(5).replace("-", "/")}</span>
                    </div>
                    <div className="schedule-day__episodes">
                      {day.episodes.length === 0 && <small className="schedule-empty">无播出</small>}
                      {day.episodes.map((episode) => (
                        <article className={`schedule-episode schedule-episode--${episode.state}`} key={episode.id}>
                          <div><strong>{episode.anime_title}</strong><small>第 {episode.episode_key} 集</small></div>
                          <time>{episode.local_time}</time>
                        </article>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {schedule.data && schedule.data.missing.length > 0 && (
            <section className="dashboard-section dashboard-attention">
              <div className="section-heading"><div><h2>缺集告警</h2><p>超过配置阈值且尚无可接受候选</p></div><CalendarDays size={18} /></div>
              <div className="compact-list">
                {schedule.data.missing.slice(0, 8).map((episode) => (
                  <Link className="compact-row" to="/subscriptions" key={episode.id}>
                    <span className="compact-row__icon compact-row__icon--danger"><AlertTriangle size={17} /></span>
                    <div><strong>{episode.anime_title} · 第 {episode.episode_key} 集</strong><small>预计 {episode.local_date} {episode.local_time}</small></div>
                    <StatusBadge status="missing" />
                    <ArrowRight className="compact-row__arrow" size={16} />
                  </Link>
                ))}
              </div>
            </section>
          )}

          {operations.data && operations.data.failed_work.length > 0 && <section className="dashboard-section dashboard-attention"><div className="section-heading"><div><h2>需要处理</h2><p>按最近发生时间汇总</p></div><Link to="/operations">查看运行中心<ArrowRight size={15} /></Link></div><div className="compact-list">{operations.data.failed_work.slice(0, 5).map((item) => <Link className="compact-row" to={item.action_path ?? "/operations"} key={item.key}><span className="compact-row__icon compact-row__icon--danger"><AlertTriangle size={17} /></span><div><strong>{item.title}</strong><small>{item.detail}{item.error_code ? ` · ${item.error_code}` : ""}</small></div><StatusBadge status="failed" /><ArrowRight className="compact-row__arrow" size={16} /></Link>)}</div></section>}

          <div className="dashboard-grid">
            <section className="dashboard-section">
              <div className="section-heading"><div><h2>订阅源状态</h2><p>按最近抓取状态排列</p></div><Link to="/feeds">查看全部<ArrowRight size={15} /></Link></div>
              {feeds.data?.length === 0 && <EmptyState icon={Rss} title="从订阅源开始" description="连接 RSS 或 Atom 后，这里会显示抓取健康状态。" action={<Link className="button button--primary button--small" to="/feeds"><Plus size={16} />添加订阅源</Link>} />}
              {feeds.data && feeds.data.length > 0 && <div className="compact-list">{feeds.data.slice(0, 6).map((feed) => <Link className="compact-row" to={`/feeds/${feed.id}`} key={feed.id}><span className="compact-row__icon"><Rss size={17} /></span><div><strong>{feed.name}</strong><small>{feed.last_success_at ? `成功抓取于${formatRelative(feed.last_success_at)}` : "等待首次抓取"}</small></div><StatusBadge status={feed.health} /><ArrowRight className="compact-row__arrow" size={16} /></Link>)}</div>}
            </section>

            <section className="dashboard-section">
              <div className="section-heading"><div><h2>最近识别的发布</h2><p>跨来源去重后的种子列表</p></div><Link to="/releases">查看全部<ArrowRight size={15} /></Link></div>
              {releases.data?.length === 0 && <EmptyState icon={Clock3} title="等待种子" description="完成一次订阅源刷新后，识别结果会出现在这里。" />}
              {releases.data && releases.data.length > 0 && <div className="compact-list">{releases.data.slice(0, 6).map((release) => <div className="compact-row" key={release.id}><span className="compact-row__icon"><Database size={17} /></span><div><strong title={release.display_name ?? release.identity_value}>{release.display_name ?? truncateHash(release.identity_value)}</strong><small>{release.source_count} 个来源 · {formatRelative(release.first_seen_at)}</small></div><span className={release.automation_eligible ? "eligibility eligibility--yes" : "eligibility"}>{release.automation_eligible ? "可靠" : "暂不可靠"}</span></div>)}</div>}
            </section>
          </div>
        </>
      )}
    </>
  );
}
