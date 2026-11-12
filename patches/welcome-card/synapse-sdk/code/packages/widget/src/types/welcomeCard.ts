/**
 * Welcome card: a card on the empty first screen, gone once the user sends a
 * message. Host `theme.welcomeCard` (embed `theme` attribute / `init({ theme })`).
 */
export type TWelcomeCardConfig = {
  /** Headline. Empty or missing -> no card. */
  title: string;
  /** One or two sentences under the headline. */
  body?: string;
  /** Up to three short step labels, drawn as numbered circles. */
  steps?: string[];
  /** Icon tile above the headline. Default "gift". */
  icon?: "gift" | "info" | "none";
  /** Shows a "maybe later" link; once used the card stays hidden for this agent in this browser. Default false (fixed). */
  dismissable?: boolean;
  /** Text of the dismiss link. Default "Maybe later". */
  dismissLabel?: string;
  /** Identifies the card for "dismissed" memory. Change it to show the card again to people who dismissed an older one. Defaults to `title`. */
  id?: string;
};
