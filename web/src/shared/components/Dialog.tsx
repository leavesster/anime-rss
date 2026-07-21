import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect } from "react";

import { Button } from "./Button";

export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-describedby={description ? "dialog-description" : undefined}
        aria-modal="true"
        className="dialog"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog__header">
          <div>
            <h2>{title}</h2>
            {description && <p id="dialog-description">{description}</p>}
          </div>
          <Button aria-label="关闭" onClick={onClose} size="icon" variant="ghost" icon={<X size={18} />} />
        </div>
        {children}
      </section>
    </div>
  );
}
