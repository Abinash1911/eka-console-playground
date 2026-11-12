import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { prefetchAgentConfig, prefetchTokenExchange } from "@synapse/core";
import type { AgentConfigResponse, ConnectionType, Environment, SYNAPSE_CONVERSATION, SynapseChannel, TContext, TInitialMessage, TokenExchangeResponse } from "@synapse/core";
import type { TRibbonConfig } from "@/types/ribbon";
import type { AgentFeedbackConfig } from "@/types/message";
import { buildStoreKey } from "@/store/medAssistStore";

export type MedAssistConfig = {
  title?: string;
  iconUrl?: string;
  onClose?: () => void;
  showCloseButton?: boolean;
  baseUrl?: string;
  environment?: Environment;
  connectionType?: ConnectionType;
  context?: TContext;
  displayMode?: "full" | "widget" | "side_panel"
  /** When true, header shows a resize toggle (full ↔ widget) and the close button is hidden. */
  resize?: boolean;
  /** Only relevant when displayMode is "side_panel". Whether the host page's own content is shifted aside ("push", default) or the panel floats on top of it ("overlay"). */
  sidePanelMode?: "push" | "overlay";
  /** Only relevant when displayMode is "side_panel". Fixed panel width in px (default 400, clamped 320-560). */
  sidePanelWidth?: number;
  /** Only relevant when displayMode is "side_panel". Which viewport edge the panel docks to. Defaults to "right", or "left" when the document is RTL. */
  side?: "left" | "right";
  /**
   * Only relevant when displayMode is "side_panel" with sidePanelMode "push". Fired
   * whenever the panel's open state (or its width/side) changes, so a host embed can
   * shift its own page layout to make room. `isPushed` is false on close/unmount —
   * always revert whatever layout change was applied when this fires false.
   */
  onSidePanelPushChange?: (isPushed: boolean, widthPx: number, side: "left" | "right") => void;
  /**
   * Partner JWT/JWE sent as auth_token in the token exchange — the only
   * host-supplied credential (carries the host's user data); absent -> guest.
   * The access (sess) and refresh tokens are issued by the exchange itself.
   */
  authToken?: string;
  /**
   * Start a new login: wipe every persisted credential and session for this
   * agent, then re-exchange from scratch. Applied once on bootstrap.
   */
  force?: boolean;
  /** When set, only these input types are shown: "text" (always), "file" (link icon), "audio" (mic icon). Omit or leave undefined to show all. */
  allowed?: (SYNAPSE_CONVERSATION)[];
  /** Greeting text + suggestion pills sourced from the agent-config API (passed through from widget-embed). */
  initialMessage?: TInitialMessage;
  /** Exit feedback configuration sourced from the agent-config API. When present, clicking close shows this form before the widget unmounts. */
  feedback?: AgentFeedbackConfig;
  /** Text the user sent from the embed's chatbox launcher; sent once as the first message after the widget connects. */
  firstUserMessage?: string;
  theme?: {
    background?: string;
    backgroundImage?: string;
    primary?: string;
    textColor?: "black" | "white";
    mode?: "light" | "dark";
    headerTinted?: boolean;
    titleImg?: string;
    tagline?: string;
    /** Host `theme.ribbon`: a one-line message under the header, fixed or dismissable. */
    ribbon?: TRibbonConfig;
    explicitDisclaimer?: boolean;
    /** Agent-config `theme.consent_content`. Host-supplied consent/disclaimer copy; falls back to the built-in paragraphs when absent. */
    consentContent?: string | string[];
    /**
     * When true, the chat is blocked behind a one-time consent form. The
     * acceptance is stored locally per agent, so it is asked once per browser.
     */
    upfrontConsent?: boolean;
    /** Agent-config `theme.tips`. Shown while the bot works on a reply, until the end of the stream; absent or empty -> built-in tips. */
    tips?: string[];
    /** When true, hides the "Powered by Eka Care" branding in the footer. Sourced from agent-config API; defaults to false (watermark visible). */
    hideWatermark?: boolean;
    /** Feature flag from agent-config API. When true, chat history UI (session drawer + fullscreen sidebar) is shown; defaults to hidden. */
    feature?: boolean;
    /** Agent-config `theme.widget_width` (px). Floating ("widget" mode, desktop) only; clamped by the widget. Overridden by `overrideWidgetWidth`. */
    widgetWidth?: number;
    /** Agent-config `theme.widget_height` (px). Floating ("widget" mode, desktop) only; clamped by the widget. Overridden by `overrideWidgetHeight`. */
    widgetHeight?: number;
    /** Host-set width (px): the `override-widget-width` attribute or `init({ theme })`. Floating only; wins over `widgetWidth`. */
    overrideWidgetWidth?: number;
    /** Host-set height (px): the `override-widget-height` attribute or `init({ theme })`. Floating only; wins over `widgetHeight`. */
    overrideWidgetHeight?: number;
    /** Where the floating (desktop "widget" mode) window opens: bottom-right "corner" (default) or "bottom-center", on the spot the embed's chatbox launcher occupied. */
    openFrom?: "corner" | "bottom-center";
  };
}
declare global {
  interface Window {
    renderMedAssist?: (container: HTMLElement, agentId: string, config: MedAssistConfig) => Root;
    /** Agent-config fetch for hosts that load the bundle as a classic script (the iframe embed). */
    fetchAgentConfig?: (config: FetchAgentConfigConfig) => Promise<AgentConfigResponse | undefined>;
    /** Token-exchange pre-warm, so hosts can start it on module load rather than at mount. */
    prefetchAuth?: (config: PrefetchAuthConfig) => Promise<TokenExchangeResponse | null>;
  }
}

// Development-only code - will be tree-shaken in production builds
if (import.meta.env.DEV && typeof document !== "undefined") {
  const rootElement = document.getElementById("root");
  if (rootElement) {
    // test passing theme to the widget
    const devConfig: MedAssistConfig = {
      title: "Medi Clinic",
      iconUrl: "https://cdn.eka.care/bot-icon.svg",
      theme: {
        primary: "#fb0909",
      },
    };
    createRoot(rootElement).render(
      <StrictMode>
        <App
          agentId={
            "NGQ2MmE3M2EtZGFhOS00OTUyLThkNmEtMGM4MDQzNWM5NGZhIzcxNzcwMDI4NjAzNzY1MDg="
          }
          config={devConfig}
        />
      </StrictMode>
    );
  }
}


export const renderMedAssist = (
  container: HTMLElement,
  agentId: string,
  config?: MedAssistConfig
): Root => {
  const cfg = config || {};
  const root = createRoot(container);
  root.render(
    <StrictMode>
      <App agentId={agentId} config={cfg} />
    </StrictMode>
  );
  return root;
};

export type PrefetchAuthConfig = {
  agentId: string;
  /** Partner JWT/JWE — the only host-supplied credential; absent -> guest. */
  authToken?: string;
  serverUrl?: string;
  environment?: Environment;
  /** Surface the widget opens in — sent as `x-channel`. Defaults to "widget". */
  channel?: SynapseChannel;
};

/** Persisted refresh token (if any) from the widget's agent-scoped sessionStorage store. */
const readPersistedTokens = (agentId: string): { refreshToken?: string; sessToken?: string } => {
  try {
    const raw = sessionStorage.getItem(buildStoreKey(agentId));
    const state = raw ? JSON.parse(raw)?.state : undefined;
    return {
      refreshToken: typeof state?.refreshToken === "string" && state.refreshToken ? state.refreshToken : undefined,
      sessToken: typeof state?.sessToken === "string" && state.sessToken ? state.sessToken : undefined,
    };
  } catch {
    return {};
  }
};

/**
 * Run the init token exchange before the widget mounts (e.g. from the embed
 * loader during idle pre-warm). The result is cached inside @synapse/core and
 * adopted by the SDK when the widget opens, so the exchange is never duplicated.
 * if no payloads are give, the backend will assumes as a guest user
 *
 * Skipped when a complete sess+refresh pair is already persisted: the SDK
 * resumes on that pair without exchanging, so the prefetch would spend a
 * request whose result nothing consumes. `force` clears the store before this
 * runs, so the no-pair branch covers it.
 */
export const prefetchAuth = (
  config: PrefetchAuthConfig
): Promise<TokenExchangeResponse | null> => {
  const { refreshToken, sessToken } = readPersistedTokens(config.agentId);
  if (refreshToken && sessToken) {
    return Promise.resolve(null);
  }
  return prefetchTokenExchange({
    ...config,
    refreshToken,
    sessToken,
  });
};

export type FetchAgentConfigConfig = {
  agentId: string;
  serverUrl?: string;
  environment?: Environment;
  /** Surface the widget opens in — sent as `x-channel`. Defaults to "widget". */
  channel?: SynapseChannel;
};

/**
 * Fetch the agent-config before the widget mounts (e.g. from the embed loader
 * during idle pre-warm). Mirrors `prefetchAuth`: the in-flight request is cached
 * inside @synapse/core and adopted by the SDK when the widget opens, so the call
 * is never duplicated.
 */
export const fetchAgentConfig = (
  config: FetchAgentConfigConfig
): Promise<AgentConfigResponse | undefined> => prefetchAgentConfig(config);

if (typeof window !== "undefined") {
  window.renderMedAssist = renderMedAssist;
  window.fetchAgentConfig = fetchAgentConfig;
  window.prefetchAuth = prefetchAuth;
}
