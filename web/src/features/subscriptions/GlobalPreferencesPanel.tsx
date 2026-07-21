import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import {
  getGlobalPreferences,
  saveGlobalPreferences,
  type PreferenceRules,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";

const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

export function GlobalPreferencesPanel() {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: ["global-preferences"], queryFn: getGlobalPreferences });
  const [groups, setGroups] = useState("");
  const [subtitles, setSubtitles] = useState("");
  const [resolutions, setResolutions] = useState("");
  const [codecs, setCodecs] = useState("");
  const [waitMinutes, setWaitMinutes] = useState(120);

  useEffect(() => {
    if (!profile.data) return;
    setGroups((profile.data.rules.preferred_groups ?? []).join(", "));
    setSubtitles((profile.data.rules.preferred_subtitles ?? []).join(", "));
    setResolutions((profile.data.rules.preferred_resolutions ?? []).join(", "));
    setCodecs((profile.data.rules.preferred_codecs ?? []).join(", "));
    setWaitMinutes(profile.data.rules.fallback_wait_minutes ?? 120);
  }, [profile.data]);

  const save = useMutation({
    mutationFn: () => {
      if (!profile.data) throw new Error("全局偏好尚未加载");
      const rules: PreferenceRules = {
        ...profile.data.rules,
        preferred_groups: split(groups),
        preferred_subtitles: split(subtitles),
        preferred_resolutions: split(resolutions),
        preferred_codecs: split(codecs),
        fallback_wait_minutes: waitMinutes,
      };
      return saveGlobalPreferences(rules, profile.data.version);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["global-preferences"] }),
        queryClient.invalidateQueries({ queryKey: ["subscriptions"] }),
      ]);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <section className="data-section preference-panel">
      <div className="section-heading">
        <div><h2>全局版本偏好</h2><p>新追番默认继承；使用覆盖的订阅保持独立。</p></div>
        <SlidersHorizontal size={19} />
      </div>
      {profile.isLoading && <LoadingState label="正在读取全局偏好" />}
      {(profile.isError || save.isError) && <ErrorBanner message={save.error?.message ?? "全局偏好加载失败。"} />}
      {profile.data && (
        <form className="preference-form" onSubmit={submit}>
          <label className="field"><span>字幕组顺序</span><input value={groups} onChange={(event) => setGroups(event.target.value)} placeholder="Nix-Raws, LoliHouse" /></label>
          <label className="field"><span>字幕顺序</span><input value={subtitles} onChange={(event) => setSubtitles(event.target.value)} /></label>
          <label className="field"><span>分辨率顺序</span><input value={resolutions} onChange={(event) => setResolutions(event.target.value)} /></label>
          <label className="field"><span>编码顺序</span><input value={codecs} onChange={(event) => setCodecs(event.target.value)} /></label>
          <label className="field preference-form__wait"><span>备选等待（分钟）</span><input type="number" min={0} max={10080} value={waitMinutes} onChange={(event) => setWaitMinutes(Number(event.target.value))} /></label>
          <Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>{save.isPending ? "保存中" : "保存"}</Button>
        </form>
      )}
    </section>
  );
}
