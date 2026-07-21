import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, TestTube2, Trash2 } from "lucide-react";
import { useState } from "react";

import { ApiError, createFeed, testFeed, type FeedCreate } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { Dialog } from "../../shared/components/Dialog";
import { ErrorBanner } from "../../shared/components/Feedback";

type HeaderRow = { id: string; name: string; value: string };

function emptyHeader(): HeaderRow {
  return { id: crypto.randomUUID(), name: "", value: "" };
}

export function FeedFormDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [interval, setInterval] = useState(600);
  const [headers, setHeaders] = useState<HeaderRow[]>([]);

  const payload = (): FeedCreate => ({
    name: name.trim(),
    url: url.trim(),
    interval_seconds: interval,
    headers: Object.fromEntries(headers.filter((header) => header.name.trim()).map((header) => [header.name.trim(), header.value])),
  });

  const testMutation = useMutation({ mutationFn: () => testFeed(payload()) });
  const createMutation = useMutation({
    mutationFn: () => createFeed(payload()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["feeds"] });
      setName("");
      setUrl("");
      setHeaders([]);
      testMutation.reset();
      onClose();
    },
  });

  const error = createMutation.error ?? testMutation.error;

  return (
    <Dialog open={open} onClose={onClose} title="添加订阅源" description="连接 RSS 或 Atom 地址，敏感 URL 与请求头会加密保存。">
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); createMutation.mutate(); }}>
        {error && <ErrorBanner message={error instanceof ApiError ? error.message : "无法连接订阅源"} />}
        <label className="field"><span>名称</span><input autoFocus required maxLength={120} placeholder="例如：Mikan 动画" value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="field"><span>订阅地址</span><input required type="url" placeholder="https://example.com/rss.xml" value={url} onChange={(event) => setUrl(event.target.value)} /></label>
        <label className="field"><span>刷新频率</span><select value={interval} onChange={(event) => setInterval(Number(event.target.value))}>
          <option value={300}>每 5 分钟</option><option value={600}>每 10 分钟</option><option value={900}>每 15 分钟</option><option value={1800}>每 30 分钟</option><option value={3600}>每 60 分钟</option>
        </select></label>

        <div className="field-group">
          <div className="field-group__heading"><div><span>自定义请求头</span><small>用于私有订阅，可留空</small></div><Button type="button" size="small" variant="ghost" icon={<Plus size={16} />} onClick={() => setHeaders((rows) => [...rows, emptyHeader()])}>添加</Button></div>
          {headers.map((header) => (
            <div className="header-row" key={header.id}>
              <input aria-label="请求头名称" placeholder="Header 名称" value={header.name} onChange={(event) => setHeaders((rows) => rows.map((row) => row.id === header.id ? { ...row, name: event.target.value } : row))} />
              <input aria-label="请求头值" placeholder="值" value={header.value} onChange={(event) => setHeaders((rows) => rows.map((row) => row.id === header.id ? { ...row, value: event.target.value } : row))} />
              <Button type="button" aria-label="删除请求头" title="删除请求头" size="icon" variant="ghost" icon={<Trash2 size={16} />} onClick={() => setHeaders((rows) => rows.filter((row) => row.id !== header.id))} />
            </div>
          ))}
        </div>

        {testMutation.data && (
          <div className="test-result">
            <div><CheckCircle2 size={18} /><strong>连接成功，发现 {testMutation.data.entry_count} 个条目</strong></div>
            {testMutation.data.preview_titles.length > 0 && <ul>{testMutation.data.preview_titles.slice(0, 3).map((title) => <li key={title}>{title}</li>)}</ul>}
          </div>
        )}

        <div className="dialog__actions">
          <Button type="button" variant="secondary" icon={<TestTube2 size={17} />} disabled={!url || testMutation.isPending} onClick={() => testMutation.mutate()}>{testMutation.isPending ? "测试中" : "测试连接"}</Button>
          <Button type="submit" variant="primary" disabled={!name || !url || createMutation.isPending}>{createMutation.isPending ? "保存中" : "保存订阅源"}</Button>
        </div>
      </form>
    </Dialog>
  );
}
