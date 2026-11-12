import { Gift, Info, Megaphone, ShieldCheck, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TRibbonConfig } from "@/types/ribbon";

const ICONS = {
  gift: Gift,
  info: Info,
  megaphone: Megaphone,
  sparkles: Sparkles,
  shield: ShieldCheck,
};

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

/** The colour if it is `#rgb` / `#rrggbb`, else undefined (so the default applies). */
function hexOrUndefined(value?: string): string | undefined {
  const v = value?.trim();
  return v && HEX.test(v) ? v : undefined;
}

/** Black or white, whichever reads better on `hex`. */
function readableOn(hex: string): string {
  const h = hex.length === 4 ? hex.replace(/./g, (c, i) => (i ? c + c : c)) : hex;
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#000000" : "#ffffff";
}

interface HeaderRibbonViewProps {
  text: string;
  icon?: TRibbonConfig["icon"];
  background?: string;
  textColor?: string;
  /** Shows the close button. */
  dismissable?: boolean;
  onDismiss?: () => void;
  className?: string;
}

export default function HeaderRibbonView({
  text,
  icon,
  background,
  textColor,
  dismissable = false,
  onDismiss,
  className,
}: HeaderRibbonViewProps) {
  const Icon = icon ? ICONS[icon] : undefined;
  const bg = hexOrUndefined(background);
  const fg = hexOrUndefined(textColor) ?? (bg ? readableOn(bg) : undefined);

  return (
    <div
      role="status"
      style={{ ...(bg && { backgroundColor: bg }), ...(fg && { color: fg }) }}
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
