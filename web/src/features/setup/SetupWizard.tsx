import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Clock3,
  Radio,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  markSetupStep,
  type InstanceSettings,
} from "../../generated/api/client";
import { CandidatePreviewStep } from "./steps/CandidatePreviewStep";
import { DownloadDefaultsStep, QbittorrentStep } from "./steps/DownloadSteps";
import { FeedStep } from "./steps/FeedStep";
import { GlobalPreferencesStep } from "./steps/GlobalPreferencesStep";
import { InstancePreferencesStep } from "./steps/InstancePreferencesStep";
import { SubscriptionStep } from "./steps/SubscriptionStep";
import { SETUP_STEPS, type SetupStepId } from "./lib";

export function SetupWizard({ settings }: { settings: InstanceSettings }) {
  const queryClient = useQueryClient();
  const completed = useMemo(() => new Set(settings.setup_completed_steps), [settings]);
  const firstIncomplete = SETUP_STEPS.findIndex((step) => !completed.has(step.id));
  const [activeIndex, setActiveIndex] = useState(Math.max(1, firstIncomplete));

  useEffect(() => {
    if (firstIncomplete >= 0) setActiveIndex(Math.max(1, firstIncomplete));
  }, [firstIncomplete]);

  const complete = async (step: SetupStepId) => {
    await markSetupStep(step);
    await queryClient.invalidateQueries({ queryKey: ["instance-settings"] });
  };
  const active = SETUP_STEPS[activeIndex];

  return (
    <div className="setup-screen">
      <header className="setup-header">
        <div className="auth-brand setup-brand">
          <span className="brand__mark"><Radio size={22} /></span>
          <div><strong>Anime RSS</strong><span>首次初始化</span></div>
        </div>
        <div className="setup-position"><Clock3 size={15} />第 {activeIndex + 1} / {SETUP_STEPS.length} 步</div>
      </header>
      <main className="setup-layout">
        <nav className="setup-progress" aria-label="初始化进度">
          {SETUP_STEPS.map((step, index) => {
            const Icon = step.icon;
            const done = completed.has(step.id);
            return (
              <button
                key={step.id}
                type="button"
                aria-current={index === activeIndex ? "step" : undefined}
                aria-label={step.label}
                title={step.label}
                className={index === activeIndex ? "setup-progress__item setup-progress__item--active" : "setup-progress__item"}
                disabled={!done || step.id === "administrator"}
                onClick={() => setActiveIndex(index)}
              >
                <span>{done ? <Check size={15} /> : <Icon size={15} />}</span>
                <small>{String(index + 1).padStart(2, "0")}</small>
                <strong>{step.label}</strong>
              </button>
            );
          })}
        </nav>
        <section className="setup-workspace" aria-labelledby="setup-step-title">
          {active.id === "instance_preferences" && <InstancePreferencesStep settings={settings} />}
          {active.id === "qbittorrent_connection" && <QbittorrentStep onComplete={() => complete(active.id)} />}
          {active.id === "download_defaults" && <DownloadDefaultsStep onComplete={() => complete(active.id)} />}
          {active.id === "feed" && <FeedStep onComplete={() => complete(active.id)} />}
          {active.id === "global_preferences" && <GlobalPreferencesStep onComplete={() => complete(active.id)} />}
          {active.id === "subscription" && <SubscriptionStep onComplete={() => complete(active.id)} />}
          {active.id === "candidate_preview" && <CandidatePreviewStep onComplete={() => complete(active.id)} />}
        </section>
      </main>
    </div>
  );
}
