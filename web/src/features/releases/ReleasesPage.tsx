import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Database, Download, PlugZap, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getDownloadConfig, listDownloadTasks, listReleases, submitReleaseDownload } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState, SuccessBanner } from "../../shared/components/Feedback";
import { PageHeader } from "../../shared/components/PageHeader";
import { formatDate, truncateHash } from "../../shared/lib/format";

export function ReleasesPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const releases = useQuery({ queryKey: ["releases"], queryFn: listReleases });
  const tasks = useQuery({ queryKey: ["download-tasks"], queryFn: listDownloadTasks });
  const downloadConfig = useQuery({ queryKey: ["download-config"], queryFn: getDownloadConfig });
  const submit = useMutation({
    mutationFn: submitReleaseDownload,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["download-tasks"] });
    },
  });
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return releases.data ?? [];
    return (releases.data ?? []).filter((release) => [release.display_name, release.identity_value, release.btih, release.btmh, release.identity_kind].some((value) => value?.toLowerCase().includes(query)));
  }, [releases.data, search]);
  const tasksByRelease = useMemo(
    () => new Map((tasks.data ?? []).map((task) => [task.release_id, task])),
    [tasks.data],
  );
  const downloaderConfigured = downloadConfig.data !== null && downloadConfig.data !== undefined;

  return (
    <>
      <PageHeader eyebrow="去重后列表" title="种子列表" description="来自多个订阅源的相同种子只保留一条，以种子哈希判断是否重复。" />
      <div className="toolbar"><label className="search-field"><Search size={17} /><input aria-label="搜索种子" placeholder="搜索种子名称、种子哈希或 BT 标识" value={search} onChange={(event) => setSearch(event.target.value)} /></label><span className="result-count">{filtered.length} 条记录</span></div>
      {(releases.isLoading || tasks.isLoading || downloadConfig.isLoading) && <LoadingState label="正在读取种子列表" />}
      {(releases.isError || tasks.isError || downloadConfig.isError) && <ErrorBanner message="种子列表、下载任务或下载器配置加载失败。" />}
      {downloadConfig.data === null && <div className="notice-strip"><PlugZap size={18} /><span>提交种子前需要先配置 qBittorrent。</span><Link className="button button--secondary button--small" to="/downloads">配置下载器</Link></div>}
      {submit.isError && <ErrorBanner message={submit.error.message || "下载任务创建失败。"} />}
      {submit.isSuccess && <SuccessBanner message="下载任务已加入队列；调度器会在后台提交到 qBittorrent。" />}
      {releases.data?.length === 0 && <EmptyState icon={Database} title="还没有种子" description="订阅源抓取成功后，包含 magnet 或 torrent 的条目会去重后显示在这里。" />}
      {releases.data && releases.data.length > 0 && filtered.length === 0 && <EmptyState icon={Search} title="没有匹配结果" description="换一个种子名称、哈希片段或清空搜索条件。" />}
      {filtered.length > 0 && <div className="data-table releases-table"><div className="data-table__head release-grid"><span>种子名称 / 种子哈希</span><span>BT 标识</span><span>来源数</span><span>是否可靠</span><span>首次发现</span><span>操作</span></div>{filtered.map((release) => {
        const task = tasksByRelease.get(release.id);
        const supported = release.automation_eligible && Boolean(release.btih);
        const pending = submit.isPending && submit.variables === release.id;
        return <div className="data-table__row release-grid" key={release.id}><div><strong title={release.display_name ?? release.identity_value}>{release.display_name ?? "名称未知"}</strong><small className="hash-value" title={release.identity_value}>{truncateHash(release.identity_value)}</small></div><span className="mono-label">{release.identity_kind.toUpperCase()}</span><strong>{release.source_count} 个</strong><span className={release.automation_eligible ? "eligibility eligibility--yes" : "eligibility"}><CheckCircle2 size={16} />{release.automation_eligible ? "可靠" : "暂不可靠"}</span><span>{formatDate(release.first_seen_at)}</span><Button size="small" variant="ghost" icon={task ? <CheckCircle2 size={15} /> : <Download size={15} />} disabled={Boolean(task) || !supported || !downloaderConfigured || submit.isPending || tasks.isLoading || tasks.isError || downloadConfig.isError} title={!supported ? "当前无法从这个 BT 标识创建下载任务" : task ? "该种子已有下载任务" : !downloaderConfigured ? "请先配置 qBittorrent" : "创建持久化下载任务"} onClick={() => submit.mutate(release.id)}>{task ? "已在队列" : !supported ? "不支持" : !downloaderConfigured ? "先配置下载器" : pending ? "排队中" : "提交下载"}</Button></div>;
      })}</div>}
    </>
  );
}
