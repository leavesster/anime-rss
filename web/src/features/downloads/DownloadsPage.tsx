import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, HardDrive, PlugZap, RefreshCw, RotateCcw, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import {
  getDownloadConfig,
  listDownloadTasks,
  processDownloads,
  retryDownloadTask,
  saveDownloadConfig,
  testDownloadConnection,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate, truncateHash } from "../../shared/lib/format";

const retryableStates = new Set(["failed", "externally_removed", "submitted"]);
const errorLabels: Record<string, string> = {
  authentication_failed: "认证失败",
  connection_failed: "连接失败",
  upstream_unavailable: "qBittorrent 暂时不可用",
  awaiting_observation: "已提交，等待读取状态",
  submission_not_observed: "已提交，未读取到状态",
  external_removal_unconfirmed: "暂未读取到任务，将再次确认",
  externally_removed: "任务已在 qBittorrent 中删除",
  operation_interrupted: "上次操作被服务重启中断",
  add_rejected: "qBittorrent 拒绝添加",
};

export function DownloadsPage() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["download-config"], queryFn: getDownloadConfig });
  const tasks = useQuery({ queryKey: ["download-tasks"], queryFn: listDownloadTasks, refetchInterval: 30_000 });
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [savePath, setSavePath] = useState("");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");

  useEffect(() => {
    if (!config.data) return;
    setBaseUrl(config.data.base_url_redacted);
    setUsername(config.data.username);
    setSavePath(config.data.default_save_path ?? "");
    setCategory(config.data.default_category ?? "");
    setTags(config.data.default_tags.join(", "));
  }, [config.data]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["download-config"] }),
      queryClient.invalidateQueries({ queryKey: ["download-tasks"] }),
    ]);
  };
  const save = useMutation({
    mutationFn: () => saveDownloadConfig({
      base_url: baseUrl,
      username,
      password: password || null,
      default_save_path: savePath || null,
      default_category: category || null,
      default_tags: tags.split(",").map((value) => value.trim()).filter(Boolean),
    }, config.data?.version),
    onSuccess: async () => { setPassword(""); await refresh(); },
  });
  const test = useMutation({ mutationFn: testDownloadConnection, onSuccess: refresh });
  const sync = useMutation({ mutationFn: processDownloads, onSuccess: refresh });
  const retry = useMutation({ mutationFn: retryDownloadTask, onSuccess: refresh });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const taskItems = tasks.data ?? [];
  const active = taskItems.filter((item) => ["planned", "retrying", "submitting", "submitted", "downloading"].includes(item.state)).length;
  const completed = taskItems.filter((item) => item.state === "completed").length;
  const attention = taskItems.filter((item) => ["failed", "externally_removed"].includes(item.state)).length;
  const hasError = config.isError || tasks.isError || save.isError || test.isError || sync.isError || retry.isError;

  return (
    <>
      <PageHeader eyebrow="下载执行" title="下载任务" description="连接 qBittorrent，提交下载任务并同步下载进度和状态。" actions={<Button variant="secondary" icon={<RefreshCw className={sync.isPending ? "spin" : ""} size={16} />} disabled={!config.data || sync.isPending} onClick={() => sync.mutate()}>立即同步</Button>} />
      {hasError && <ErrorBanner message="下载操作未完成，请检查连接配置和任务错误状态。" />}
      {(config.isLoading || tasks.isLoading) && <LoadingState label="正在读取下载状态" />}
      {!config.isLoading && !tasks.isLoading && <>
        <section className="overview-band overview-band--four" aria-label="下载指标">
          <div className="overview-metric"><span className="metric-icon metric-icon--green"><PlugZap size={19} /></span><div><small>qBittorrent</small><strong>{config.data?.last_success_at && !config.data.last_error_code ? "已连接" : "未连接"}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--blue"><Download size={19} /></span><div><small>处理中</small><strong>{active}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--gray"><CheckCircle2 size={19} /></span><div><small>已完成</small><strong>{completed}</strong></div></div>
          <div className="overview-metric"><span className="metric-icon metric-icon--red"><AlertTriangle size={19} /></span><div><small>需要处理</small><strong>{attention}</strong></div></div>
        </section>

        <section className="download-config data-section">
          <div className="section-heading"><div><h2>qBittorrent 连接</h2><p>{config.data ? `${config.data.base_url_redacted} · 最近成功 ${formatDate(config.data.last_success_at)}` : "尚未配置"}</p></div>{config.data && <StatusBadge status={config.data.last_success_at && !config.data.last_error_code ? "connected" : "failed"} />}</div>
          <form className="download-config__form" onSubmit={submit}>
            <label className="field"><span>Web API 地址</span><input type="url" required value={baseUrl} placeholder="http://192.168.1.10:8080" onChange={(event) => setBaseUrl(event.target.value)} /></label>
            <label className="field"><span>用户名</span><input required value={username} autoComplete="username" onChange={(event) => setUsername(event.target.value)} /></label>
            <label className="field"><span>密码</span><input type="password" required={!config.data?.password_configured} value={password} autoComplete="current-password" placeholder={config.data?.password_configured ? "保留现有密码" : "输入密码"} onChange={(event) => setPassword(event.target.value)} /></label>
            <label className="field"><span>默认保存目录</span><input value={savePath} placeholder="/downloads/anime" onChange={(event) => setSavePath(event.target.value)} /></label>
            <label className="field"><span>分类</span><input value={category} placeholder="anime" onChange={(event) => setCategory(event.target.value)} /></label>
            <label className="field"><span>标签</span><input value={tags} placeholder="rss, seasonal" onChange={(event) => setTags(event.target.value)} /></label>
            <div className="download-config__actions"><Button type="button" variant="secondary" icon={<PlugZap size={16} />} disabled={!config.data || test.isPending} onClick={() => test.mutate()}>{test.data ? `已连接 ${test.data.version}` : "测试连接"}</Button><Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>{save.isPending ? "保存中" : "保存配置"}</Button></div>
          </form>
        </section>

        <section className="data-section download-task-section">
          <div className="section-heading"><div><h2>任务状态</h2><p>共 {taskItems.length} 个下载任务</p></div></div>
          {taskItems.length === 0 ? <EmptyState icon={HardDrive} title="还没有下载任务" description="自动选择版本或手动提交发布条目后，任务会在这里等待提交到 qBittorrent。" /> : <div className="download-list">
            {taskItems.map((task) => <article className="download-row" key={task.id}>
              <div className="download-row__identity"><strong title={task.display_name ?? task.info_hash}>{task.display_name ?? truncateHash(task.info_hash)}</strong><small><span className="download-row__hash">{truncateHash(task.info_hash)}</span> · {task.actual_save_path ?? task.requested_save_path ?? "使用 qBittorrent 默认路径"}</small></div>
              <div className="download-progress"><div><span style={{ width: `${Math.round(task.progress * 100)}%` }} /></div><small>{Math.round(task.progress * 100)}%</small></div>
              <div className="download-row__meta"><small>{task.category || "无分类"}</small><strong>{task.tags.join(", ") || "无标签"}</strong></div>
              <div className="download-row__state"><StatusBadge status={task.state} />{task.stale && <small>未能读取到最新状态</small>}{task.error_code && <small>{errorLabels[task.error_code] ?? task.error_code}</small>}</div>
              <div className="download-row__time"><small>上次读取到状态</small><strong>{formatDate(task.last_observed_at)}</strong></div>
              {retryableStates.has(task.state) ? <Button aria-label="重试任务" title="重试任务" size="icon" variant="ghost" icon={<RotateCcw size={16} />} disabled={retry.isPending} onClick={() => retry.mutate(task.id)} /> : <span className="download-row__spacer" />}
            </article>)}
          </div>}
        </section>
      </>}
    </>
  );
}
