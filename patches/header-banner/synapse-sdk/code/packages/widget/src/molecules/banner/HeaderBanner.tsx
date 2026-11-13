import { cn } from "@/lib/utils";

interface HeaderBannerProps {
  text: string;
  className?: string;
}

/** One line of text under the header. Colours come from the accent colour (`primary`). */
export default function HeaderBanner({ text, className }: HeaderBannerProps) {
  return (
    <div
      role="status"
      className={cn(
        "synapse-header-banner flex-shrink-0 px-4 py-2 bg-primary text-primary-foreground text-xs font-medium text-balance",
        className
      )}
    >
      {text}
    </div>
  );
}
