import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { TMessageOptions } from "@/types/message";

interface Suggestion {
  label?: string;
  value?: string;
  response?: string;
}

/** Returns a warm, time-of-day-aware health/self-care greeting (no name). */
function getTimeBasedGreeting(): string {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return "Good morning. How are you feeling today?";
  if (hour >= 12 && hour < 17) return "Good afternoon. How are you feeling right now?";
  if (hour >= 17 && hour < 21) return "Good evening. How are you doing this evening?";
  return "Up late? I'm here whenever you need me.";
}

/** When the description is longer than this, hide it and show only the salutation. */
const DESCRIPTION_MAX_LENGTH = 180;

interface EmptyStateFullScreenProps {
  title: string;
  description?: string;
  suggestions?: Suggestion[];
  onSendMessage: (options: TMessageOptions) => Promise<void>;
  disabled?: boolean;
  /** Composer slot — rendered below suggestions in the Figma-styled card. */
  composer?: ReactNode;
  /** Optional content rendered inside the composer card (e.g. Powered by branding). */
  composerFooter?: ReactNode;
  /** Connection-status / retry banner — rendered above the composer card so the
   * user can recover from disconnects while still on the empty-state screen. */
  connectionBanner?: ReactNode;
  /** Welcome card (host `theme.welcomeCard`) — rendered above the greeting. */
  welcomeCard?: ReactNode;
}

export default function EmptyStateFullScreen({
  description,
  suggestions,
  onSendMessage,
  disabled,
  composer,
  composerFooter,
  connectionBanner,
  welcomeCard,
}: EmptyStateFullScreenProps) {
  const handleClick = (suggestion: Suggestion) => {
    const label = suggestion.label || suggestion.value || "";
    if (!label) return;
    onSendMessage({
      message: suggestion.value || label,
      messageId: Date.now().toString(),
    });
  };

  return (
    <div className="flex-1 flex flex-col overflow-y-auto">
      <div className="flex flex-col items-stretch gap-6 w-full max-w-2xl mx-auto my-auto px-4 py-6">
        {welcomeCard}
        <div className="flex flex-col px-3 gap-2 items-start">
          {description && description?.trim?.()?.length <= DESCRIPTION_MAX_LENGTH && (
            <h2
              className="text-text-primary"
              style={{
                fontFamily:
                  "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                fontSize: 36,
                lineHeight: "40px",
                fontWeight: 500,
                letterSpacing: "-0.025em",
                margin: 0,
              }}
            >
              {getTimeBasedGreeting()}
            </h2>
          )}
          {description && (
            <p
              className="text-text-primary"
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: 16,
                lineHeight: "24px",
                fontWeight: 400,
                margin: 0,
              }}
            >
              {description}
            </p>
          )}
        </div>

        {suggestions && suggestions.length > 0 && (
          <div className="content-center px-3 flex flex-wrap gap-4 items-center">
            {suggestions.map((suggestion, i) => {
              const label = suggestion.label || suggestion.value || "";
              if (!label) return null;
              return (
                <button
                  key={`${label}-${i}`}
                  type="button"
                  onClick={() => handleClick(suggestion)}
                  disabled={disabled}
                  className={cn(
                    "inline-flex items-center bg-white border border-primary text-primary",
                    "rounded-lg overflow-clip whitespace-nowrap transition-colors shrink-0",
                    "supports-[hover:hover]:hover:bg-primary supports-[hover:hover]:hover:text-primary-foreground",
                    disabled
                      ? "opacity-50 cursor-not-allowed"
                      : "cursor-pointer"
                  )}
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: 16,
                    lineHeight: "24px",
                    fontWeight: 500,
                    padding: "8px 12px",
                    WebkitTapHighlightColor: "transparent",
                    outline: "none",
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}

        {connectionBanner}

        {composer && (
          <div>
            {composer}
            {composerFooter}
          </div>
        )}
      </div>
    </div>
  );
}
