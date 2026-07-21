import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function StepFrame({
  icon: Icon,
  title,
  summary,
  children,
}: {
  icon: LucideIcon;
  title: string;
  summary: string;
  children: ReactNode;
}) {
  return (
    <>
      <header className="setup-step__header">
        <span><Icon size={20} /></span>
        <div><h1 id="setup-step-title">{title}</h1><p>{summary}</p></div>
      </header>
      <div className="setup-step__body">{children}</div>
    </>
  );
}
