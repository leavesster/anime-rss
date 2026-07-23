import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Check,
  Clock3,
  Download,
  FileArchive,
  LogOut,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  createBackup,
  getNotificationConfig,
  getInstanceSettings,
  listBackups,
  listNotifications,
  logout,
  markNotificationRead,
  saveNotificationConfig,
  saveInstanceSettings,
  stageRestore,
  testNotificationWebhook,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function SystemPage() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["notification-config"], queryFn: getNotificationConfig });
  const instance = useQuery({ queryKey: ["instance-settings"], queryFn: getInstanceSettings });
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: listNotifications, refetchInterval: 30_000 });
  const backups = useQuery({ queryKey: ["backups"], queryFn: listBackups });
  const [webhookEnabled, setWebhookEnabled] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [bearerToken, setBearerToken] = useState("");
  const [restorePending, setRestorePending] = useState(false);
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [missingGraceHours, setMissingGraceHours] = useState(24);
  const restoreInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!config.data) return;
    setWebhookEnabled(config.data.webhook_enabled);
    setWebhookUrl(config.data.webhook_url_redacted ?? "");
  }, [config.data]);

  useEffect(() => {
    if (!instance.data) return;
    setTimezone(instance.data.timezone);
    setMissingGraceHours(instance.data.missing_episode_grace_hours);
  }, [instance.data]);

  const refreshNotifications = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["notification-config"] }),
      queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    ]);
  };
  const saveConfig = useMutation({
    mutationFn: () => saveNotificationConfig(
      {
        webhook_enabled: webhookEnabled,
        webhook_url: webhookUrl || null,
        bearer_token: bearerToken || null,
      },
      config.data?.version,
    ),
    onSuccess: async () => { setBearerToken(""); await refreshNotifications(); },
  });
  const testWebhook = useMutation({ mutationFn: testNotificationWebhook, onSuccess: refreshNotifications });
  const saveInstance = useMutation({
    mutationFn: () => saveInstanceSettings(
      {
        timezone,
        interface_language: "zh-CN",
        missing_episode_grace_hours: missingGraceHours,
      },
      instance.data?.version ?? 0,
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["instance-settings"] }),
        queryClient.invalidateQueries({ queryKey: ["schedule-calendar"] }),
      ]);
    },
  });
  const markRead = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const makeBackup = useMutation({
    mutationFn: createBackup,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["backups"] }),
  });
  const restore = useMutation({
    mutationFn: stageRestore,
    onSuccess: () => setRestorePending(true),
  });
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear();
      window.location.reload();
    },
  });
  const submitConfig = (event: FormEvent) => {
    event.preventDefault();
    saveConfig.mutate();
  };
  const submitInstance = (event: FormEvent) => {
    event.preventDefault();
    saveInstance.mutate();
  };
  const onRestore = () => {
    const file = restoreInput.current?.files?.[0];
    if (file) restore.mutate(file);
  };
  const hasError = config.isError || instance.isError || notifications.isError || backups.isError
    || saveConfig.isError || saveInstance.isError || testWebhook.isError || makeBackup.isError || restore.isError;

  return (
    <>
      <PageHeader
        eyebrow="实例管理"
        title="系统设置"
        description="通知、数据恢复和管理员会话。"
        actions={<Button variant="ghost" icon={<LogOut size={16} />} disabled={signOut.isPending} onClick={() => signOut.mutate()}>退出登录</Button>}
      />
      {hasError && <ErrorBanner message="系统设置操作未完成，请检查输入和服务状态。" />}
      {restorePending && <div className="notice-strip"><RotateCcw size={17} /><span>恢复文件已验证并暂存，重启服务后生效。</span></div>}
      {(config.isLoading || instance.isLoading || notifications.isLoading || backups.isLoading) && <LoadingState label="正在读取系统设置" />}
      {!config.isLoading && !instance.isLoading && !notifications.isLoading && !backups.isLoading && (
        <div className="system-layout">
          <section className="system-section">
            <div className="section-heading">
              <div><h2>地区与缺集判断</h2><p>所有存储时间保持 UTC，界面按这里转换</p></div>
              <Clock3 size={18} />
            </div>
            <form className="system-form" onSubmit={submitInstance}>
              <label className="field">
                <span>时区</span>
                <input list="timezone-options" value={timezone} onChange={(event) => setTimezone(event.target.value)} />
                <datalist id="timezone-options">
                  <option value="Asia/Shanghai" />
                  <option value="Asia/Tokyo" />
                  <option value="Asia/Hong_Kong" />
                  <option value="Asia/Taipei" />
                  <option value="UTC" />
                </datalist>
              </label>
              <label className="field">
                <span>缺集宽限时间</span>
                <input type="number" min={1} max={168} value={missingGraceHours} onChange={(event) => setMissingGraceHours(Number(event.target.value))} />
                <small>预计播出后等待小时数</small>
              </label>
              <div className="system-actions">
                <Button type="submit" size="small" variant="primary" icon={<Save size={15} />} disabled={saveInstance.isPending}>保存</Button>
              </div>
            </form>
          </section>

          <section className="system-section">
            <div className="section-heading">
              <div><h2>通知</h2><p>站内消息与 Webhook 投递</p></div>
              <Bell size={18} />
            </div>
            <form className="system-form" onSubmit={submitConfig}>
              <label className="toggle-field">
                <input type="checkbox" checked={webhookEnabled} onChange={(event) => setWebhookEnabled(event.target.checked)} />
                <span><strong>Webhook</strong><small>{config.data?.last_success_at ? `最近成功 ${formatDate(config.data.last_success_at)}` : "未验证"}</small></span>
              </label>
              <label className="field">
                <span>接收地址</span>
                <input type="url" required={webhookEnabled || Boolean(config.data)} value={webhookUrl} placeholder="https://notify.example/hook" onChange={(event) => setWebhookUrl(event.target.value)} />
              </label>
              <label className="field">
                <span>Bearer Token</span>
                <input type="password" value={bearerToken} autoComplete="new-password" placeholder={config.data?.bearer_token_configured ? "留空保留现有 Token" : "可选"} onChange={(event) => setBearerToken(event.target.value)} />
              </label>
              <div className="system-actions">
                <Button type="button" size="small" icon={<Send size={15} />} disabled={!config.data?.webhook_enabled || testWebhook.isPending} onClick={() => testWebhook.mutate()}>测试</Button>
                <Button type="submit" size="small" variant="primary" icon={<Save size={15} />} disabled={saveConfig.isPending}>保存</Button>
              </div>
            </form>
          </section>

          <section className="system-section">
            <div className="section-heading">
              <div><h2>备份与恢复</h2><p>数据库、配置密钥和运行历史</p></div>
              <ShieldCheck size={18} />
            </div>
            <div className="backup-actions">
              <Button variant="primary" icon={<FileArchive size={16} />} disabled={makeBackup.isPending} onClick={() => makeBackup.mutate()}>创建备份</Button>
              <input ref={restoreInput} className="visually-hidden" type="file" accept=".backup,application/zip" onChange={onRestore} />
              <Button icon={<RotateCcw size={16} />} disabled={restore.isPending} onClick={() => restoreInput.current?.click()}>恢复备份</Button>
            </div>
            <div className="backup-list">
              {(backups.data ?? []).map((backup) => (
                <article key={backup.filename}>
                  <FileArchive size={17} />
                  <div><strong>{backup.reason === "scheduled" ? "自动备份" : backup.reason === "pre-restore" ? "恢复前备份" : "手动备份"}</strong><small>{formatDate(backup.created_at)} · {formatBytes(backup.size_bytes)}</small></div>
                  <a aria-label="下载备份" title="下载备份" href={`/api/v1/system/backups/${encodeURIComponent(backup.filename)}`}><Download size={16} /></a>
                </article>
              ))}
              {(backups.data?.length ?? 0) === 0 && <p className="inline-note">暂无备份</p>}
            </div>
          </section>

          <section className="system-section system-section--wide">
            <div className="section-heading">
              <div><h2>站内消息</h2><p>{(notifications.data ?? []).filter((item) => !item.read_at).length} 条未读</p></div>
              <Button size="icon" variant="ghost" title="刷新消息" aria-label="刷新消息" icon={<RefreshCw size={16} />} onClick={() => notifications.refetch()} />
            </div>
            {(notifications.data?.length ?? 0) === 0 ? (
              <EmptyState icon={Bell} title="暂无消息" description="自动选择、下载和运行异常会显示在这里。" />
            ) : (
              <div className="notification-list">
                {notifications.data?.map((item) => (
                  <article className={item.read_at ? "notification-row" : "notification-row notification-row--unread"} key={item.id}>
                    <span className={`notification-level notification-level--${item.level}`} />
                    <div><strong>{item.title}</strong><p>{item.message}</p><small>{formatDate(item.created_at)}{item.delivery_state ? ` · Webhook ${item.delivery_state}` : ""}</small></div>
                    <StatusBadge status={item.level} />
                    {!item.read_at ? <Button size="icon" variant="ghost" aria-label="标记已读" title="标记已读" icon={<Check size={16} />} disabled={markRead.isPending} onClick={() => markRead.mutate(item.id)} /> : <span className="notification-spacer" />}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
