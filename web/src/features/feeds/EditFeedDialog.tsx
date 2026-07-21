import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, type Feed, updateFeed } from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { Dialog } from "../../shared/components/Dialog";
import { ErrorBanner } from "../../shared/components/Feedback";

export function EditFeedDialog({ feed, open, onClose }: { feed: Feed; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(feed.name);
  const [interval, setInterval] = useState(feed.interval_seconds);
  const [replacementUrl, setReplacementUrl] = useState("");

  useEffect(() => {
    if (open) {
      setName(feed.name);
      setInterval(feed.interval_seconds);
      setReplacementUrl("");
    }
  }, [feed, open]);

  const mutation = useMutation({
    mutationFn: () => updateFeed(feed.id, feed.version, {
      name: name.trim(),
      interval_seconds: interval,
      ...(replacementUrl.trim() ? { url: replacementUrl.trim() } : {}),
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["feeds"] });
      onClose();
    },
  });

  return (
    <Dialog open={open} onClose={onClose} title="编辑订阅源" description="留空新地址会继续使用当前加密地址。">
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
        {mutation.error && <ErrorBanner message={mutation.error instanceof ApiError ? mutation.error.message : "保存失败"} />}
        <label className="field"><span>名称</span><input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="field"><span>当前地址</span><input disabled value={feed.url_redacted} /></label>
        <label className="field"><span>替换地址 <small>可选</small></span><input type="url" placeholder="输入后会替换当前地址" value={replacementUrl} onChange={(event) => setReplacementUrl(event.target.value)} /></label>
        <label className="field"><span>刷新频率</span><select value={interval} onChange={(event) => setInterval(Number(event.target.value))}>
          <option value={300}>每 5 分钟</option><option value={600}>每 10 分钟</option><option value={900}>每 15 分钟</option><option value={1800}>每 30 分钟</option><option value={3600}>每 60 分钟</option>
        </select></label>
        <div className="dialog__actions"><Button type="button" onClick={onClose}>取消</Button><Button type="submit" variant="primary" disabled={!name.trim() || mutation.isPending}>{mutation.isPending ? "保存中" : "保存修改"}</Button></div>
      </form>
    </Dialog>
  );
}
