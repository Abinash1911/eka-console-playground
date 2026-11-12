/**
 * Header ribbon: a one-line message under the header. Host `theme.ribbon`
 * (embed `theme` attribute / `init({ theme })`).
 */
export type TRibbonConfig = {
  /** The message. Empty or missing -> no ribbon. */
  text: string;
  /** Shows a close button; once closed it stays closed for this agent in this browser. Default false (fixed). */
  dismissable?: boolean;
  /** Small icon before the text. Default none. */
  icon?: "gift" | "info";
  /** Identifies the message for "closed" memory. Change it to show the ribbon again to people who closed an older one. Defaults to `text`. */
  id?: string;
};
