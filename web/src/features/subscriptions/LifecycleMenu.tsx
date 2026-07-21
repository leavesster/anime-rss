import { Archive, CircleCheck, MoreHorizontal, Pause, Play, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type SubscriptionState = "following" | "paused" | "completed" | "archived";

const actions: Record<SubscriptionState, { state: SubscriptionState; label: string; icon: typeof Play }[]> = {
  following: [
    { state: "paused", label: "暂停追番", icon: Pause },
    { state: "completed", label: "标记完结", icon: CircleCheck },
    { state: "archived", label: "归档", icon: Archive },
  ],
  paused: [
    { state: "following", label: "恢复追番", icon: Play },
    { state: "completed", label: "标记完结", icon: CircleCheck },
    { state: "archived", label: "归档", icon: Archive },
  ],
  completed: [
    { state: "following", label: "重新追番", icon: RotateCcw },
    { state: "archived", label: "归档", icon: Archive },
  ],
  archived: [
    { state: "paused", label: "恢复为暂停", icon: RotateCcw },
  ],
};

export function LifecycleMenu({
  state,
  disabled,
  onChange,
}: {
  state: SubscriptionState;
  disabled?: boolean;
  onChange: (state: SubscriptionState) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  return (
    <div className="lifecycle-menu" ref={root}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="订阅生命周期操作"
        className="icon-button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        title="订阅生命周期操作"
        type="button"
      >
        <MoreHorizontal size={17} />
      </button>
      {open && <div className="lifecycle-menu__items" role="menu">
        {actions[state].map((action) => {
          const Icon = action.icon;
          return (
            <button
              disabled={disabled}
              key={action.state}
              onClick={() => {
                setOpen(false);
                onChange(action.state);
              }}
              role="menuitem"
              type="button"
            >
              <Icon size={15} />
              {action.label}
            </button>
          );
        })}
      </div>}
    </div>
  );
}
