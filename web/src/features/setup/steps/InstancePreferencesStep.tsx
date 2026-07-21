import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Languages, Save } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  saveInstanceSettings,
  type InstanceSettings,
} from "../../../generated/api/client";
import { Button } from "../../../shared/components/Button";
import { ErrorBanner } from "../../../shared/components/Feedback";
import { StepFrame } from "../StepFrame";

export function InstancePreferencesStep({ settings }: { settings: InstanceSettings }) {
  const queryClient = useQueryClient();
  const [timezone, setTimezone] = useState(settings.timezone);
  const [language, setLanguage] = useState(settings.interface_language);
  const save = useMutation({
    mutationFn: () => saveInstanceSettings({
      timezone,
      interface_language: language,
      missing_episode_grace_hours: settings.missing_episode_grace_hours,
    }, settings.version),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["instance-settings"] });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <StepFrame icon={Languages} title="地区与语言" summary="实例时间显示和界面语言">
      {save.isError && <ErrorBanner message={save.error.message} />}
      <form className="setup-form" onSubmit={submit}>
        <label className="field">
          <span>时区</span>
          <input list="setup-timezones" required value={timezone} onChange={(event) => setTimezone(event.target.value)} />
          <datalist id="setup-timezones">
            <option value="Asia/Shanghai" /><option value="Asia/Tokyo" />
            <option value="Asia/Hong_Kong" /><option value="Asia/Taipei" /><option value="UTC" />
          </datalist>
        </label>
        <label className="field">
          <span>界面语言</span>
          <select value={language} onChange={(event) => setLanguage(event.target.value)}>
            <option value="zh-CN">简体中文</option><option value="en">English</option>
          </select>
        </label>
        <div className="setup-form__actions">
          <Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>保存并继续</Button>
        </div>
      </form>
    </StepFrame>
  );
}
