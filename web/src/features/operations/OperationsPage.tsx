import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Clock3, History, RefreshCw, ServerCog } from "lucide-react";
import { Link } from "react-router-dom";

import {
  getOperationsOverview,
  listAuditEvents,
  listJobRuns,
  listScheduledJobs,
  runSchedulerNow,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate, formatRelative } from "../../shared/lib/format";

export function OperationsPage() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["operations-overview"], queryFn: getOperationsOverview, refetchInterval: 15_000 });
  const jobs = useQuery({ queryKey: ["scheduled-jobs"], queryFn: listScheduledJobs, refetchInterval: 15_000 });
  const runs = useQuery({ queryKey: ["job-runs"], queryFn: listJobRuns, refetchInterval: 15_000 });
  const audit = useQuery({ queryKey: ["audit-events"], queryFn: listAuditEvents, refetchInterval: 30_000 });
  const runNow = useMutation({
    mutationFn: runSchedulerNow,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["operations-overview"] }),
        queryClient.invalidateQueries({ queryKey: ["scheduled-jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["job-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-events"] }),
      ]);
    },
  });
  const loading = overview.isLoading || jobs.isLoading || runs.isLoading || audit.isLoading;
  const failed = overview.isError || jobs.isError || runs.isError || audit.isError || runNow.isError;
  const latestRuns = runs.data?.slice(0, 12) ?? [];
  const hasFailure = overview.data?.failed_work.some((item) => item.attention_kind === "failure") ?? false;

  return (
    <>
      <PageHeader eyebrow="运行维护" title="运行状态" description="先处理业务异常；底层作业和审计记录保留在高级诊断中。" actions={<Button variant="secondary" title="执行所有已经到期的抓取、选择、通知和下载任务" icon={<RefreshCw className={runNow.isPending ? "spin" : ""} size={16} />} disabled={runNow.isPending} onClick={() => runNow.mutate()}>{runNow.isPending ? "正在运行" : "运行到期任务"}</Button>} />
      {loading && <LoadingState label="正在读取运行状态" />}
      {failed && <ErrorBanner message="部分运行诊断暂时无法加载。" />}
      {overview.data && jobs.data && runs.data && audit.data && <>
        <section className="overview-band overview-band--four" aria-label="运行指标">
          <div className="overview-metric"><span className="metric-icon metric-icon--green"><Activity size={19} /></span><div><small>调度器</small><strong>{overview.data.scheduler?.state ?? "starting"}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--blue"><Clock3 size={19} /></span><div><small>已安排任务</small><strong>{overview.data.pending_jobs}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--gray"><CheckCircle2 size={19} /></span><div><small>最近成功</small><strong>{latestRuns.filter((item) => item.status === "success").length}</strong></div></div>
          <div className="overview-metric"><span className={`metric-icon ${hasFailure ? "metric-icon--red" : overview.data.failed_work.length ? "metric-icon--amber" : "metric-icon--gray"}`}><AlertTriangle size={19} /></span><div><small>需要处理</small><strong>{overview.data.failed_work.length}</strong></div></div>
        </section>

        <section className="data-section operations-section">
          <div className="section-heading"><div><h2>依赖状态</h2><p>可选外部系统不会影响服务就绪探针</p></div><small>最近调度 {formatRelative(overview.data.scheduler?.last_success_at)}</small></div>
          <div className="dependency-grid">{overview.data.dependencies.map((item) => <article key={item.key}><span className="dependency-icon"><ServerCog size={18} /></span><div><strong>{item.label}</strong><small>{item.summary}</small></div><StatusBadge status={item.status} /></article>)}</div>
        </section>

        <section className="data-section operations-section">
          <div className="section-heading"><div><h2>需要处理</h2><p>聚合抓取、识别、下载和调度失败</p></div></div>
          {overview.data.failed_work.length === 0 ? <EmptyState icon={CheckCircle2} title="没有待处理事项" description="当前没有失败任务或需要确认的单集。" /> : <div className="failure-list">{overview.data.failed_work.map((item) => <article key={item.key}><StatusBadge status={item.attention_kind === "failure" ? "failed" : "needs_confirmation"} /><div><strong title={item.title}>{item.title}</strong><small>{item.detail}</small></div><time>{formatDate(item.occurred_at)}</time>{item.action_path ? <Link to={item.action_path}>处理</Link> : null}</article>)}</div>}
        </section>

        <details className="diagnostics-details">
          <summary>高级诊断 <span>作业、运行记录和原始审计标识</span></summary>
          <div className="operations-grid">
            <section className="data-section operations-section">
              <div className="section-heading"><div><h2>后台任务</h2><p>计划执行时间和当前状态</p></div></div>
              <div className="runtime-list">{jobs.data.map((job) => <article key={job.id}><div><strong>{job.job_kind}</strong><small>{job.dedupe_key}</small></div><div><small>下次执行</small><strong>{formatDate(job.due_at)}</strong></div><StatusBadge status={job.last_error_code ? "failed" : job.lease_owner ? "running" : "pending"} /></article>)}</div>
            </section>

            <section className="data-section operations-section">
              <div className="section-heading"><div><h2>运行记录</h2><p>记录每次后台任务的运行结果</p></div><History size={17} /></div>
              <div className="runtime-list">{latestRuns.map((run) => <article key={run.id}><div><strong>{run.job_kind}</strong><small>{run.error_code ?? `${run.dedupe_key} · #${run.attempt}`}</small></div><div><small>开始时间</small><strong>{formatDate(run.started_at)}</strong></div><StatusBadge status={run.status} /></article>)}</div>
            </section>
          </div>

          <section className="data-section operations-section">
            <div className="section-heading"><div><h2>审计历史</h2><p>自动决策和管理员命令的追加式记录</p></div></div>
            <div className="audit-list">{audit.data.slice(0, 20).map((event) => <article key={event.id}><span className="audit-event">{event.event_type}</span><div><strong>{event.entity_type}</strong><small>{event.entity_id}</small></div><time>{formatDate(event.created_at)}</time></article>)}</div>
          </section>
        </details>
      </>}
    </>
  );
}
