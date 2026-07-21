import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FolderDown, PlugZap, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import {
  getDownloadConfig,
  saveDownloadConfig,
  testDownloadConnection,
} from "../../../generated/api/client";
import { Button } from "../../../shared/components/Button";
import { ErrorBanner, LoadingState } from "../../../shared/components/Feedback";
import { splitList } from "../lib";
import { StepFrame } from "../StepFrame";

function useDownloadForm() {
  const config = useQuery({ queryKey: ["download-config"], queryFn: getDownloadConfig });
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8080");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [savePath, setSavePath] = useState("");
  const [category, setCategory] = useState("anime");
  const [tags, setTags] = useState("anime-rss");
  useEffect(() => {
    if (!config.data) return;
    setBaseUrl(config.data.base_url_redacted);
    setUsername(config.data.username);
    setSavePath(config.data.default_save_path ?? "");
    setCategory(config.data.default_category ?? "");
    setTags(config.data.default_tags.join(", "));
  }, [config.data]);
  return {
    config, baseUrl, setBaseUrl, username, setUsername, password, setPassword,
    savePath, setSavePath, category, setCategory, tags, setTags,
  };
}

export function QbittorrentStep({ onComplete }: { onComplete: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const form = useDownloadForm();
  const connect = useMutation({
    mutationFn: async () => {
      await saveDownloadConfig({
        base_url: form.baseUrl,
        username: form.username,
        password: form.password || null,
        default_save_path: form.savePath || null,
        default_category: form.category || null,
        default_tags: splitList(form.tags),
      }, form.config.data?.version);
      const result = await testDownloadConnection();
      await onComplete();
      return result;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["download-config"] });
    },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); connect.mutate(); };

  return (
    <StepFrame icon={Download} title="连接 qBittorrent" summary="Web API 连接与能力验证">
      {form.config.isLoading && <LoadingState label="正在读取下载配置" />}
      {(form.config.isError || connect.isError) && <ErrorBanner message={connect.error?.message ?? "下载配置读取失败"} />}
      {!form.config.isLoading && <form className="setup-form" onSubmit={submit}>
        <label className="field"><span>Web API 地址</span><input type="url" required value={form.baseUrl} onChange={(event) => form.setBaseUrl(event.target.value)} /></label>
        <div className="setup-form__columns">
          <label className="field"><span>用户名</span><input required value={form.username} onChange={(event) => form.setUsername(event.target.value)} /></label>
          <label className="field"><span>密码</span><input type="password" required={!form.config.data?.password_configured} placeholder={form.config.data?.password_configured ? "留空保留现有密码" : ""} value={form.password} onChange={(event) => form.setPassword(event.target.value)} /></label>
        </div>
        <div className="setup-form__actions">
          <Button type="submit" variant="primary" icon={<PlugZap size={16} />} disabled={connect.isPending}>{connect.isPending ? "正在验证" : "验证并继续"}</Button>
        </div>
      </form>}
    </StepFrame>
  );
}

export function DownloadDefaultsStep({ onComplete }: { onComplete: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const form = useDownloadForm();
  const save = useMutation({
    mutationFn: async () => {
      if (!form.config.data) throw new Error("qBittorrent 尚未配置");
      await saveDownloadConfig({
        base_url: form.baseUrl,
        username: form.username,
        password: null,
        default_save_path: form.savePath || null,
        default_category: form.category || null,
        default_tags: splitList(form.tags),
      }, form.config.data.version);
      await onComplete();
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["download-config"] });
    },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); save.mutate(); };
  return (
    <StepFrame icon={FolderDown} title="下载默认值" summary="新下载任务采用的路径、分类和标签">
      {form.config.isLoading && <LoadingState label="正在读取下载配置" />}
      {(form.config.isError || save.isError) && <ErrorBanner message={save.error?.message ?? "下载配置读取失败"} />}
      {form.config.data && <form className="setup-form" onSubmit={submit}>
        <label className="field"><span>默认保存目录</span><input value={form.savePath} onChange={(event) => form.setSavePath(event.target.value)} placeholder="/downloads/anime" /></label>
        <div className="setup-form__columns">
          <label className="field"><span>默认分类</span><input value={form.category} onChange={(event) => form.setCategory(event.target.value)} /></label>
          <label className="field"><span>默认标签 <small>逗号分隔</small></span><input value={form.tags} onChange={(event) => form.setTags(event.target.value)} /></label>
        </div>
        <div className="setup-form__actions"><Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>保存并继续</Button></div>
      </form>}
    </StepFrame>
  );
}
