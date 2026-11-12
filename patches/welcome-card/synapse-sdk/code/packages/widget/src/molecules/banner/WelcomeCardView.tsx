import { Gift, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TWelcomeCardConfig } from "@/types/welcomeCard";

const MAX_STEPS = 3;

interface WelcomeCardViewProps {
  title: string;
  body?: string;
  steps?: string[];
  icon?: TWelcomeCardConfig["icon"];
  dismissable?: boolean;
  dismissLabel?: string;
  onDismiss?: () => void;
  className?: string;
}

export default function WelcomeCardView({
  title,
  body,
  steps,
  icon = "gift",
  dismissable = false,
  dismissLabel = "Maybe later",
  onDismiss,
  className,
}: WelcomeCardViewProps) {
  const Icon = icon === "gift" ? Gift : icon === "info" ? Info : null;
  const shownSteps = (steps ?? []).filter((s) => s.trim()).slice(0, MAX_STEPS);

  return (
    <section
      aria-label={title}
      className={cn(
        "synapse-welcome-card flex flex-col items-center gap-2 rounded-2xl border border-border-subtle bg-surface px-4 pt-5 pb-3 text-center shadow-sm",
        className
      )}
    >
      {Icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
          <Icon className="w-6 h-6" aria-hidden="true" />
        </div>
      )}
      <h3 className="text-base font-semibold text-text-primary">{title}</h3>
      {body && <p className="text-sm text-text-secondary text-balance">{body}</p>}
      {shownSteps.length > 0 && (
        <ol className="mt-1 flex w-full justify-center gap-4">
          {shownSteps.map((step, i) => (
            <li key={`${step}-${i}`} className="flex w-20 flex-col items-center gap-1 text-xs text-text-secondary">
              <span
                className="flex h-6 w-6 items-center justify-center rounded-full font-semibold text-primary"
                style={{ backgroundColor: "hsl(var(--primary) / 0.1)" }}
              >
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      )}
      {dismissable && (
        <button
          type="button"
          onClick={onDismiss}
          className="mt-1 text-xs text-text-secondary underline underline-offset-2"
        >
          {dismissLabel}
        </button>
      )}
    </section>
  );
}
