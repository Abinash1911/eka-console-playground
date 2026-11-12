/**
 * Header ribbon: a one-line message under the header. Host `theme.ribbon`
 * (embed `theme` attribute / `init({ theme })`), or the agent-config API.
 */
export type TRibbonConfig = {
  /** The message. Empty or missing -> no ribbon. */
  text: string;
  /** Shows a close button; once closed it stays closed for this agent in this browser. Default false (fixed). */
  dismissable?: boolean;
  /** Small icon before the text. Default none. */
  icon?: "gift" | "info" | "megaphone" | "sparkles" | "shield";
  /** Background colour as hex (`#rgb` or `#rrggbb`). Default: the agent's accent colour. Anything else is ignored. */
  background?: string;
  /** Text and icon colour as hex. Default: black or white, whichever reads better on the background. Anything else is ignored. */
  textColor?: string;
  /** Identifies the message for "closed" memory. Change it to show the ribbon again to people who closed an older one. Defaults to `text`. */
  id?: string;
};
