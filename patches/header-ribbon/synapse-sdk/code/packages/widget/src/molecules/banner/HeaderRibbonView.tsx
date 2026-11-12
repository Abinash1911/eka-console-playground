import { Gift, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TRibbonConfig } from "@/types/ribbon";

interface HeaderRibbonViewProps {
  text: string;
  icon?: TRibbonConfig["icon"];
  /** Shows the close button. */
  dismissable?: boolean;
  onDismiss?: () => void;
  className?: string;
}

export default function HeaderRibbonView({
  text,
  icon,
  dismissable = false,
  onDismiss,
  className,
}: HeaderRibbonViewProps) {
  const Icon = icon === "gift" ? Gift : icon === "info" ? Info : null;

  return (
    <div
      role="status"
      className={cn(
        "synapse-header-ribbon flex flex-shrink-0 items-center gap-2 px-4 py-2 bg-primary text-primary-foreground text-xs font-medium",
        className
      )}
    >
      {Icon && <Icon className="w-4 h-4 flex-shrink-0" aria-hidden="true" />}
      <span className="flex-1 min-w-0 text-balance">{text}</span>
      {dismissable && (
        <button
          type="button"
          onClick={onDismiss}
          title="Dismiss"
          aria-label="Dismiss"
          className="flex-shrink-0 rounded-full p-0.5 opacity-80 hover:opacity-100 transition-opacity"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
