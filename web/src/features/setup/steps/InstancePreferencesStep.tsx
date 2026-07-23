import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock3, Save } from "lucide-react";
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
  const save = useMutation({
    mutationFn: () => saveInstanceSettings({
      timezone,
      interface_language: "zh-CN",
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
    <StepFrame icon={Clock3} title="地区设置" summary="实例时间显示">
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
        <div className="setup-form__actions">
          <Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>保存并继续</Button>
        </div>
      </form>
    </StepFrame>
  );
}
