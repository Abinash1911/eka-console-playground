const getCurrentScript = (): HTMLScriptElement | null => {
  if (typeof document === "undefined") {
    console.error("document is not defined");
    return null;
  }

  const { currentScript } = document;
  if (currentScript instanceof HTMLScriptElement) {
    return currentScript;
  }

  // Fallback for when document.currentScript isn't available. On a real host
  // page with many other async scripts (analytics, ads, ...), blindly taking
  // the *last* <script> tag is unreliable — it can silently grab an unrelated
  // tag, missing data-widget-assets and falling back to the CDN asset base
  // even when the host explicitly asked for local assets. Prefer a tag that
  // unambiguously looks like this loader before resorting to that guess.
  const scripts = Array.from(document.getElementsByTagName("script"));
  const marked = scripts.find((s) => s.hasAttribute("data-widget-assets"));
  if (marked) return marked;
  const byFilename = scripts.filter((s) => /(^|\/)index\.js(\?.*)?$/.test(s.src));
  if (byFilename.length) return byFilename[byFilename.length - 1];

  return scripts.length ? scripts[scripts.length - 1] : null;
};

type WidgetEnvironment = "production" | "development" | "staging";

const getEnvironment = (
  value: string | null
): WidgetEnvironment | undefined => {
  if (
    value === "production" ||
    value === "development" ||
    value === "staging"
  ) {
    return value;
  }
  return undefined;
};

const scriptEl = getCurrentScript();

// Detect version tag from script src (e.g., @dev, @latest)
const DEFAULT_WIDGET_ASSET_BASE = (() => {
  if (scriptEl?.src?.includes("@dev")) {
    return "https://cdn.jsdelivr.net/npm/@eka-care/medassist-widget@dev/dist/";
  }
  return "https://cdn.jsdelivr.net/npm/@eka-care/medassist-widget@latest/dist/";
})();

/** Theme from agent-config API (has mode; textColor derived: dark → black, light → white) */
enum FeedbackTypeEnum {
  DEFAULT = "default",
  NPS = "nps",
}

type TOptions = { label: string; value: string };
type AgentConfig = {
  name?: string;
  allowed?: ("text" | "file" | "audio" | "voice")[];
  nudge?: boolean;
  connectivity?: "http_stream" | "socket";
  resize?: boolean;
  theme?: {
    background?: string;
    background_img?: string;
    accent?: string;
    mode?: "light" | "dark";
    header_tinted?: boolean;
    title_img?: string;
    icon_img?: string
    nudge_color?: string;
    tagline?: string;
    /** Header ribbon: a one-line message under the header. Absent or empty `text` -> none. */
    ribbon?: {
      text?: string;
      dismissable?: boolean;
      icon?: "gift" | "info" | "megaphone" | "sparkles" | "shield";
      /** Hex colour. Absent -> the accent colour. */
      background?: string;
      /** Hex colour. Absent -> black or white, whichever reads better. */
      text_color?: string;
      id?: string;
    };
    hide_watermark?: boolean;
    explicit_disclaimer?: boolean;
    /** Host-supplied consent/disclaimer copy (paragraph list, or one blob with newlines). Absent -> the widget's built-in copy. */
    consent_content?: string | string[];
    /** When true, the widget asks for upfront consent once before the chat is usable. */
    upfront_consent?: boolean;
    /** Tips shown while the bot works on a reply. Absent or empty -> the widget's built-in tips. */
    tips?: string[];
    /** Feature flag — currently gates the chat-history UI (session drawer + fullscreen sidebar). */
    feature?: boolean;
    /** Floating-widget width in px (desktop "widget" mode only). Clamped by the widget. */
    widget_width?: number;
    /** Floating-widget height in px (desktop "widget" mode only). Clamped by the widget. */
    widget_height?: number;
    /** How the closed widget is shown ("widget" mode only). Host `launcher-type` wins. Default "button". */
    launcher_type?: "button" | "chatbox";
    /** Launcher CSS, applied over the defaults. Host `custom-launcher-styles` wins over it. */
    launcher_styles?: string;
  }
  initial_message?: {
    text?: string;
    suggestions?: { label?: string; value?: string; response?: string }[];
  };
  feedback?: {
    type: FeedbackTypeEnum;
    title?: string;
    description?: string;
    form?: {
      default?: TOptions[];
      detractors?: TOptions[];
      passives?: TOptions[];
      promoters?: TOptions[];
    }
  };
  /** Client-side flag set when the user clicks "Don't show again" on the feedback modal. */
  feedback_hidden?: boolean;
};

type MedAssistInitConfig = {
  /** Partner JWT/JWE — the only host-supplied credential; absent -> guest. */
  authToken?: string;
  agentId?: string;
  context?: Record<string, unknown>;
  title?: string;
  iconUrl?: string;
  baseUrl?: string;
  resize?: boolean;
  displayMode?: "full" | "widget" | "side_panel";
  /** Only relevant when displayMode is "side_panel". Whether the host page's own content is shifted aside ("push", default) or the panel floats on top of it ("overlay"). */
  sidePanelMode?: "push" | "overlay";
  /** Only relevant when displayMode is "side_panel". Fixed panel width in px (default 400, clamped 320-560). */
  sidePanelWidth?: number;
  /** Only relevant when displayMode is "side_panel". Which viewport edge the panel docks to. Defaults to "right", or "left" when the document is RTL. */
  side?: "left" | "right";
  customLauncherStyles?: string;
  /** "widget" mode only. "chatbox" shows a message box instead of the round button; the widget opens on send. Default "button". */
  launcherType?: "button" | "chatbox";
  redirectUrl?: string;
  showCloseButton?: boolean;
  theme?: {
    backgroundImage?: string;
    primary?: string;
    textColor?: "black" | "white";
    mode?: "light" | "dark";
    headerTinted?: boolean;
    titleImg?: string;
    tagline?: string;
    /** Header ribbon (see the widget package's `TRibbonConfig`). */
    ribbon?: { text: string; dismissable?: boolean; icon?: "gift" | "info" | "megaphone" | "sparkles" | "shield"; background?: string; textColor?: string; id?: string };
    explicitDisclaimer?: boolean;
    consentContent?: string | string[];
    upfrontConsent?: boolean;
    tips?: string[];
    feature?: boolean;
    /** Floating-widget size (px) from the agent config. Overridden by the `override…` keys below. */
    widgetWidth?: number;
    widgetHeight?: number;
    /** Host-set floating-widget size (px). Wins over the agent config. */
    overrideWidgetWidth?: number;
    overrideWidgetHeight?: number;
  };
  [key: string]: unknown;
};

/** Map agent-config API theme to widget theme (mode → textColor: dark→black, light→white) */
function mapAgentConfigThemeToWidgetTheme(apiTheme: AgentConfig["theme"] | undefined): MedAssistInitConfig["theme"] {
  if (!apiTheme) return undefined;
  const textColor = apiTheme.mode === "dark" ? "white" : apiTheme.mode === "light" ? "black" : undefined;
  return {
    ...(apiTheme.background_img && { backgroundImage: apiTheme.background_img }),
    ...(apiTheme.accent && { primary: apiTheme.accent }),
    ...(textColor && { textColor }),
    ...(apiTheme.mode && { mode: apiTheme.mode }),
    ...(apiTheme.header_tinted !== undefined && { headerTinted: apiTheme.header_tinted }),
    ...(apiTheme.title_img && { titleImg: apiTheme.title_img }),
    ...(apiTheme.tagline && { tagline: apiTheme.tagline }),
    ...(apiTheme.ribbon?.text?.trim() && {
      ribbon: {
        text: apiTheme.ribbon.text,
        ...(apiTheme.ribbon.dismissable !== undefined && { dismissable: apiTheme.ribbon.dismissable }),
        ...(apiTheme.ribbon.icon && { icon: apiTheme.ribbon.icon }),
        ...(apiTheme.ribbon.background && { background: apiTheme.ribbon.background }),
        ...(apiTheme.ribbon.text_color && { textColor: apiTheme.ribbon.text_color }),
        ...(apiTheme.ribbon.id && { id: apiTheme.ribbon.id }),
      },
    }),
    ...(apiTheme.hide_watermark && { hideWatermark: apiTheme.hide_watermark }),
    ...(apiTheme.explicit_disclaimer && { explicitDisclaimer: apiTheme.explicit_disclaimer }),
    ...(apiTheme.consent_content && { consentContent: apiTheme.consent_content }),
    ...(apiTheme.upfront_consent && { upfrontConsent: apiTheme.upfront_consent }),
    ...(apiTheme.tips?.length && { tips: apiTheme.tips }),
    ...(apiTheme.feature !== undefined && { feature: apiTheme.feature }),
    ...(typeof apiTheme.widget_width === "number" && { widgetWidth: apiTheme.widget_width }),
    ...(typeof apiTheme.widget_height === "number" && { widgetHeight: apiTheme.widget_height })
  };
}

/** Preload an image by URL so it is cached and loads faster when the widget uses it. */
function preloadImage(url: string): void {
  if (!url || typeof document === "undefined") return;
  try {
    const link = document.createElement("link");
    link.rel = "preload";
    link.as = "image";
    link.href = url;
    document.head.appendChild(link);
  } catch {
    // fallback: use Image to prime cache
    const img = new Image();
    img.src = url;
  }
}

/**
 * How the widget is presented → the `x-channel` value sent on every API call:
 * floating window → "widget", fullscreen → "web", docked panel → "side_panel".
 * Mirrors `channelFromDisplayMode` in the widget package (the loader is built
 * without a bundler, so it cannot import from @synapse/core).
 */
type SynapseChannel = "widget" | "web" | "side_panel";

function channelFromDisplayMode(displayMode: string | null | undefined): SynapseChannel {
  if (displayMode === "full") return "web";
  if (displayMode === "side_panel") return "side_panel";
  return "widget";
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

/**
 * Icon colour on the accent: near-black on light accents, near-white on dark
 * ones — the HSL-lightness > 50% rule of the widget's calculateForegroundColor.
 * Non-hex colours can't be measured here and get near-white.
 */
function colorOnAccent(color: string): string {
  const hex = color.trim().replace("#", "");
  const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;
  if (!/^[0-9a-f]{6}$/i.test(full)) return "#fafafa";
  const channels = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  const lightness = (Math.max(...channels) + Math.min(...channels)) / 2;
  return lightness > 0.5 ? "#171717" : "#fafafa";
}

/** Normalizes the `display-mode` attribute value to one of the three supported modes. */
function normalizeDisplayMode(value: string | null | undefined): "full" | "widget" | "side_panel" {
  if (value === "full") return "full";
  if (value === "side_panel") return "side_panel";
  return "widget";
}


// ---------------------------------------------------------------------------
// Nudge types & helpers
// ---------------------------------------------------------------------------

type NudgeApiResponse = {
  url_pattern?: {
    domain?: string;
    path?: string;
  };
  nudges?: string[];
  delay?: number;
  expiry?: number;
};

type NudgePathData = {
  nudges: string[];
  expiry: number;
  delay: number;
};

/**
 * localStorage shape:
 * {
 *   [agentId]: {
 *     [domain (url.host)]: {
 *       [path]: NudgePathData
 *     }
 *   }
 * }
 */
type NudgeLocalStore = {
  [agentId: string]: {
    [domain: string]: {
      [path: string]: NudgePathData;
    };
  };
};

const NUDGE_STORAGE_KEY = "eka-medassist-nudges";
const AGENT_CONFIG_CACHE_KEY = "eka-medassist-agent-config";

function readAgentConfigCache(agentId: string): AgentConfig | undefined {
  try {
    const raw = localStorage.getItem(AGENT_CONFIG_CACHE_KEY);
    const store: Record<string, AgentConfig> = raw ? JSON.parse(raw) : {};
    return store[agentId];
  } catch {
    return undefined;
  }
}

function writeAgentConfigCache(agentId: string, config: AgentConfig): void {
  try {
    const raw = localStorage.getItem(AGENT_CONFIG_CACHE_KEY);
    const store: Record<string, AgentConfig> = raw ? JSON.parse(raw) : {};
    // Merge rather than replace so client-side flags (e.g. feedback_hidden) survive a cache refresh.
    store[agentId] = { ...(store[agentId] || {}), ...config };
    localStorage.setItem(AGENT_CONFIG_CACHE_KEY, JSON.stringify(store));
  } catch {
    // non-critical; ignore storage errors
  }
}

function getNudgeStore(): NudgeLocalStore {
  try {
    const raw = localStorage.getItem(NUDGE_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function setNudgeStore(store: NudgeLocalStore): void {
  try {
    localStorage.setItem(NUDGE_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // ignore storage errors
  }
}

function normalizePath(pathname: string): string {
  let p = pathname.replace(/\/+$/, "");
  if (!p.startsWith("/")) p = "/" + p;
  return p || "/";
}

type NudgeCacheHit = { domain: string; path: string; data: NudgePathData };

/**
 * Build path candidates from the most specific path back to "/" by stripping
 * one segment at a time. e.g. /abc/efg/ff → ["/abc/efg/ff", "/abc/efg", "/abc", "/"]
 */
function getNudgePathCandidates(pathname: string): string[] {
  const segments = pathname.split("/").filter(Boolean);
  const candidates: string[] = [];
  for (let i = segments.length; i >= 0; i--) {
    candidates.push(i === 0 ? "/" : "/" + segments.slice(0, i).join("/"));
  }
  return candidates;
}

/**
 * Look up a cached nudge for the given path candidates (checked in order, most
 * specific first). Also matches the wildcard variant of each candidate
 * (e.g. "/abc/*"). Returns the first match, or null.
 */
function findCachedNudgeForCandidates(
  agentId: string,
  url: URL,
  candidates: string[]
): NudgeCacheHit | null {
  const store = getNudgeStore();
  const agentNudges = store[agentId];
  if (!agentNudges) return null;

  const domain = url.host;
  const domainNudges = agentNudges[domain];
  if (!domainNudges) return null;

  for (const candidate of candidates) {
    if (domainNudges[candidate] !== undefined) {
      return { domain, path: candidate, data: domainNudges[candidate] };
    }
    // Also check wildcard variant (e.g. "/*" or "/abc/*")
    const wildcard = candidate === "/" ? "/*" : candidate + "/*";
    if (domainNudges[wildcard] !== undefined) {
      return { domain, path: wildcard, data: domainNudges[wildcard] };
    }
  }

  return null;
}

/**
 * Like findCachedNudgeForCandidates, but drops (and clears) an expired hit so
 * callers always get a still-valid cached nudge or null.
 */
function findFreshCachedNudge(
  agentId: string,
  url: URL,
  candidates: string[]
): NudgeCacheHit | null {
  const hit = findCachedNudgeForCandidates(agentId, url, candidates);
  if (!hit) return null;
  const now = Math.floor(Date.now() / 1000);
  if (hit.data.expiry <= now) {
    clearNudgeForPath(agentId, hit.domain, hit.path);
    return null;
  }
  return hit;
}

function clearNudgeForPath(agentId: string, domain: string, path: string): void {
  const store = getNudgeStore();
  const agentNudges = store[agentId];
  if (!agentNudges || !agentNudges[domain]) return;
  delete agentNudges[domain][path];
  setNudgeStore(store);
}

function storeNudgeResponse(
  agentId: string,
  response: NudgeApiResponse,
  visitedPath?: string
): void {
  const domain = response?.url_pattern?.domain;
  const path = response?.url_pattern?.path;
  if (!response.nudges?.length || !response.expiry || !domain || !path) return;

  const store = getNudgeStore();
  if (!store[agentId]) store[agentId] = {};
  if (!store[agentId][domain]) store[agentId][domain] = {};

  const data: NudgePathData = {
    nudges: response.nudges,
    expiry: response.expiry,
    delay: response.delay ?? 5,
  };
  store[agentId][domain][path] = data;
  // Also cache under the exact path that triggered this API call (when the
  // matched pattern is broader, e.g. "/*"), so a refresh of this page is a
  // primary cache hit while a never-visited path still consults the API for a
  // possibly more specific pattern.
  if (visitedPath && visitedPath !== path) {
    store[agentId][domain][visitedPath] = data;
  }
  setNudgeStore(store);
}

// ---------------------------------------------------------------------------
// Nudge cookie helpers  (1-day TTL, keyed by agentId, value: "open" | "closed")
// ---------------------------------------------------------------------------

const NUDGE_COOKIE_PREFIX = "eka-nudge";

function setNudgeCookie(agentId: string, value: "open" | "closed"): void {
  const expires = new Date(Date.now() + 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `${NUDGE_COOKIE_PREFIX}-${agentId}=${value}; expires=${expires}; path=/; SameSite=Lax`;
}

function getNudgeCookie(agentId: string): "open" | "closed" | null {
  const match = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${NUDGE_COOKIE_PREFIX}-${agentId}=`));
  if (!match) return null;
  const value = match.split("=")[1];
  return value === "open" || value === "closed" ? value : null;
}

/** Widget store key (sessionStorage, agent-scoped) — mirrors `buildStoreKey` in the widget package. */
const WIDGET_STORE_KEY_PREFIX = "med-assist-store-";

/** Sess (access) token persisted by the widget store, if the widget already ran in this tab. */
function readPersistedSessToken(agentId: string): string | undefined {
  try {
    const raw = sessionStorage.getItem(`${WIDGET_STORE_KEY_PREFIX}${agentId}`);
    const sessToken = raw ? JSON.parse(raw)?.state?.sessToken : undefined;
    return typeof sessToken === "string" && sessToken ? sessToken : undefined;
  } catch {
    return undefined;
  }
}

async function fetchNudgeData(
  agentId: string,
  sessToken: string,
  baseUrl?: string,
  channel: SynapseChannel = "widget"
): Promise<NudgeApiResponse | undefined> {

  const url = `${baseUrl}/med-assist/user-nudge`;

  const metaTags: { name?: string; property?: string; content?: string }[] = [];
  if (typeof document !== "undefined") {
    document.querySelectorAll("meta").forEach((meta) => {
      const name = meta.getAttribute("name") ?? undefined;
      const property = meta.getAttribute("property") ?? undefined;
      const content = meta.getAttribute("content") ?? undefined;
      if (name || property) metaTags.push({ name, property, content });
    });
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-agent-id": agentId,
        "x-channel": channel,
        "referer": typeof window !== "undefined" ? window.location.href : "",
        "Authorization": `Bearer ${sessToken}`,
      },
      body: JSON.stringify({
        meta_tags: metaTags,
        // url:"https://apollohospitals.com/doctors/cardiologist/neha-dr?abc=1&refe=eka.care"
        url: typeof window !== "undefined" ? window.location.href : "",
      }),
    });
    if (!res.ok) return undefined;
    return await res.json() as NudgeApiResponse;
  } catch {
    return undefined;
  }
}

/**
 * Chatbox placeholders read as an open invitation, so each ends in "…".
 * Nudge / suggestion / host strings arrive without one: a trailing "." or
 * "..." becomes "…"; one that already ends in "…", "?" or "!" is left as is
 * ("Need help booking?…" reads wrong).
 */
function withTrailingEllipsis(text: string): string {
  const t = text.trim();
  if (/[…?!]$/.test(t)) return t;
  return `${t.replace(/\.+$/, "")}…`;
}

type ReactRoot = { unmount: () => void };

/**
 * Window event fired whenever side-panel push mode shifts (or un-shifts) the
 * host page. `detail` is a {@link SidePanelPushDetail}.
 */
const SIDE_PANEL_PUSH_EVENT = "eka-medassist:side-panel-push";

type SidePanelPushDetail = {
  /** true when the panel just opened and the host was pushed; false on close. */
  pushed: boolean;
  /** Panel width in px (the amount the host is shifted by). */
  width: number;
  /** Which viewport edge the panel is docked to. */
  side: "left" | "right";
};

interface EkaMedAssistWindow extends Window {
  EkaMedAssist?: {
    init: (config: MedAssistInitConfig) => void;
    onClose?: () => void;
    /**
     * Side-panel push mode only. Called with `true` when the panel opens and
     * the host <body> has been shifted, and with `false` when it closes and the
     * shift is reverted — a host can adjust its own `position: fixed` chrome
     * here. The same signal is also dispatched as the
     * `eka-medassist:side-panel-push` window event.
     */
    onSidePanelPushChange?: (pushed: boolean, widthPx: number, side: "left" | "right") => void;
  };
  __ekaMedAssistConfig__?: MedAssistInitConfig;
  renderMedAssist?: (container: HTMLElement, agentId: string, config: MedAssistInitConfig) => ReactRoot;
}

const globalMedAssistConfig: MedAssistInitConfig = {};

const getWidgetElement = (): HTMLElement | null => {
  if (typeof document === "undefined") {
    return null;
  }
  return document.querySelector("eka-medassist-widget");
};

if (typeof window !== "undefined") {
  const w = window as EkaMedAssistWindow;
  w.__ekaMedAssistConfig__ = globalMedAssistConfig;

  w.EkaMedAssist = {
    init(config: MedAssistInitConfig) {
      Object.assign(globalMedAssistConfig, config);
      const el = getWidgetElement();
      if (!el) return;

      if (config.agentId) el.setAttribute("agent-id", config.agentId);
      if (config.authToken) el.setAttribute("auth-token", config.authToken);
      if (config.title) el.setAttribute("title", config.title);
      if (config.iconUrl) el.setAttribute("icon-url", config.iconUrl);
      if (config.baseUrl) el.setAttribute("base-url", config.baseUrl);
      if (config.resize !== undefined) el.setAttribute("resize", String(config.resize));
      // displayMode "full" → open immediately fullscreen via openFromBridge() below.
      if (config.displayMode === "full" || config.displayMode === "widget" || config.displayMode === "side_panel") {
        el.setAttribute("display-mode", config.displayMode);
      }
      if (config.sidePanelMode) el.setAttribute("side-panel-mode", config.sidePanelMode);
      if (config.sidePanelWidth !== undefined) el.setAttribute("side-panel-width", String(config.sidePanelWidth));
      if (config.side) el.setAttribute("side", config.side);
      if (config.context) {
        try {
          el.setAttribute("context", JSON.stringify(config.context));
        } catch {
          console.warn("Failed to stringify context passed to init");
        }
      }

      if (typeof config.customLauncherStyles === "string") {
        el.setAttribute("custom-launcher-styles", config.customLauncherStyles);
      }
      if (config.launcherType) el.setAttribute("launcher-type", config.launcherType);

      if (config.redirectUrl) el.setAttribute("redirect-url", config.redirectUrl);

      if (config.theme?.backgroundImage) {
        preloadImage(config.theme.backgroundImage);
      }

      (el as any).openFromBridge?.();
    },
  };
}

const scriptBaseUrl = (() => {
  if (!scriptEl) {
    return "";
  }
  try {
    return new URL(".", scriptEl.src || window.location.href).href;
  } catch {
    return "";
  }
})();

const widgetAssetBaseUrl = (() => {
  if (!scriptEl) {
    return DEFAULT_WIDGET_ASSET_BASE;
  }

  const dataValue = scriptEl.dataset.widgetAssets;
  if (dataValue === "local") {
    return `${scriptBaseUrl}src/`;
  }

  if (dataValue && dataValue.length > 0) {
    try {
      return new URL(dataValue, scriptBaseUrl).href;
    } catch {
      return dataValue.endsWith("/") ? dataValue : `${dataValue}/`;
    }
  }

  return DEFAULT_WIDGET_ASSET_BASE;
})();

const WIDGET_JS_URL = `${widgetAssetBaseUrl}medassist-widget.js`;
const WIDGET_CSS_URL = `${widgetAssetBaseUrl}medassist-widget.css`;

/**
 * Token-exchange result. `null` when the widget short-circuited the prefetch
 * because a complete sess+refresh pair was already persisted.
 */
type PrefetchAuthResult = { sess_token?: string } | null | undefined;

type WidgetModule = {
  renderMedAssist: (container: HTMLElement, agentId: string, config: MedAssistInitConfig) => ReactRoot;
  prefetchAuth?: (config: {
    agentId: string;
    authToken?: string;
    serverUrl?: string;
    environment?: WidgetEnvironment;
    channel?: SynapseChannel;
  }) => Promise<PrefetchAuthResult>;
  /** Agent-config fetch owned by the SDK (URL, headers and envelope live in @synapse/core). */
  fetchAgentConfig?: (config: {
    agentId: string;
    serverUrl?: string;
    environment?: WidgetEnvironment;
    channel?: SynapseChannel;
  }) => Promise<AgentConfig | undefined>;
};
let widgetModulePromise: Promise<WidgetModule> | null = null;
let widgetCssTextPromise: Promise<string> | null = null;

/** Start fetching widget CSS (shared promise). Used for preload and by loadWidgetCss. */
function getWidgetCssTextPromise(): Promise<string> {
  if (!widgetCssTextPromise) {
    widgetCssTextPromise = fetch(WIDGET_CSS_URL).then((response) => {
      if (!response.ok) {
        throw new Error(
          `Unable to fetch widget styles from ${WIDGET_CSS_URL}`
        );
      }
      return response.text();
    });
  }
  return widgetCssTextPromise;
}

class MedAssistWidgetLoader extends HTMLElement {
  private widgetLoaded: boolean;
  private displayMode: "full" | "widget" | "side_panel";
  private hostPushStyleEl: HTMLStyleElement | null = null;
  /** Current host push, or null when the host is not shifted. See applyHostPush. */
  private hostPushState: { width: number; side: "left" | "right" } | null = null;
  private reactRoot: { unmount: () => void } | null = null;
  private agentConfigPromise: Promise<AgentConfig | undefined> | null = null;
  private loading = false;
  /** True once the widget has been opened from this launcher: closing it then leaves a chat in progress. */
  private chatStarted = false;
  private placeholderTimer: ReturnType<typeof setInterval> | null = null;
  private placeholderIndex = 0;

  /**
   * Launcher visual state:
   * - "idle"    → icon, clickable
   * - "loading" → spinner in the launcher's place, clicks ignored
   * - "open"    → hidden (widget is mounted)
   */
  private setLauncherState(state: "idle" | "loading" | "open"): void {
    this.launcherState = state;
    this.updateLauncherView();
  }

  private launcherState: "idle" | "loading" | "open" = "idle";

  /**
   * Launcher kind: host `launcher-type` attribute / init({ launcherType }),
   * then agent-config `theme.launcher_type` (cached copy), then "button".
   * The chatbox exists only in floating "widget" mode.
   */
  private getLauncherType(): "button" | "chatbox" {
    if (this.displayMode !== "widget") return "button";
    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};
    const agentId = this.getAgentId();
    const value =
      this.getAttribute("launcher-type") ||
      (initConfig.launcherType as string | undefined) ||
      (agentId ? readAgentConfigCache(agentId)?.theme?.launcher_type : undefined);
    return value === "chatbox" ? "chatbox" : "button";
  }

  private isChatboxShown(): boolean {
    return this.getLauncherType() === "chatbox";
  }

  /**
   * Show the button or the chatbox for the current launcher state:
   * - "idle"    → chatbox (or button when the launcher is a button)
   * - "loading" → button: spinner in its place; chatbox: "sending" look, input locked
   * - "open"    → both hidden (widget is mounted)
   */
  private updateLauncherView(): void {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) return;
    this.applyCustomLauncherStyles();
    const state = this.launcherState;
    const showChatbox = this.isChatboxShown();

    const button = shadowRoot.getElementById("medassist-open-btn");
    if (button) {
      const loading = state === "loading" && !showChatbox;
      button.classList.toggle("loading", loading);
      button.classList.toggle("hidden", state === "open" || showChatbox);
      if (loading) {
        button.setAttribute("aria-busy", "true");
      } else {
        button.removeAttribute("aria-busy");
      }
    }

    const chatbox = shadowRoot.getElementById("medassist-chatbox");
    if (chatbox) {
      this.applyChatboxTheme(chatbox);
      const sending = state === "loading" && showChatbox;
      chatbox.classList.toggle("hidden", state === "open" || !showChatbox);
      chatbox.classList.toggle("sending", sending);
      const continuing = this.chatStarted && state === "idle";
      chatbox.classList.toggle("continuing", continuing);
      this.syncChatboxPlaceholder();
      this.syncChatboxPulse();
      const input = shadowRoot.getElementById("medassist-chatbox-input") as HTMLInputElement | null;
      if (input) {
        input.readOnly = sending || continuing;
        // Mounted: the message now lives in the widget.
        if (state === "open") {
          input.value = "";
          this.autosizeChatbox();
        }
        const send = chatbox.querySelector<HTMLButtonElement>(".medassist-chatbox-send");
        if (send) send.disabled = !input.value.trim();
      }
    }
  }

  /**
   * `x-channel` for every request this loader makes, from how the widget is set
   * to open. The attribute wins; `init({ displayMode })` covers calls made
   * during idle pre-warm, before init() has stamped the attribute on.
   */
  private getChannel(): SynapseChannel {
    const fromAttribute = this.getAttribute("display-mode");
    if (fromAttribute) return channelFromDisplayMode(fromAttribute);
    const initConfig = typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined;
    return channelFromDisplayMode(initConfig?.displayMode);
  }

  /**
   * Agent-config, fetched by the SDK — the endpoint path, headers and response
   * envelope all live in @synapse/core, so nothing about the API is duplicated
   * here. The loader is built without a bundler and cannot import core, so it
   * reaches the SDK through the widget module it already loads; that module's
   * download is started at idle pre-warm (and again at the top of
   * loadAndRender), so it is normally in flight or cached by the time this runs.
   */
  private getAgentConfig(): Promise<AgentConfig | undefined> {
    if (!this.agentConfigPromise) {
      const initConfig = (typeof window !== "undefined"
        ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
        : undefined) || {};
      const serverUrl =
        (initConfig.baseUrl as string) ||
        this.getAttribute("base-url") ||
        "https://matrix.eka.care/reloaded";
      const agentId =
        (initConfig.agentId as string) || this.getAttribute("agent-id") || "";
      if (!agentId) return Promise.resolve(undefined);
      const environment =
        getEnvironment(this.getAttribute("environment")) ?? "production";
      this.agentConfigPromise = this.loadWidgetModule()
        .then((module) =>
          module.fetchAgentConfig?.({
            agentId,
            serverUrl,
            environment,
            channel: this.getChannel(),
          })
        )
        .catch(() => {
          // Non-fatal: fall back to attribute + init theme. Drop the memo so a
          // later call retries instead of replaying the rejection.
          this.agentConfigPromise = null;
          return undefined;
        });
    }
    return this.agentConfigPromise;
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.widgetLoaded = false;
    this.displayMode = normalizeDisplayMode(this.getAttribute("display-mode"));

    // Listen for AUTH_EXPIRED events from the widget and forward to parent
    this.setupAuthExpirationListener();
  }

  static get observedAttributes(): string[] {
    return ["icon-url", "display-mode", "custom-launcher-styles", "redirect-url", "side-panel-mode", "side-panel-width", "side", "override-widget-width", "override-widget-height", "launcher-type"];
  }

  connectedCallback(): void {
    if (this.displayMode === "full") {
      this.initializeFullMode();
      // loadAndRender fetches CSS + JS in parallel and only mounts after the
      // CSS is injected into the shadow root, so no FOUC.
      this.loadAndRender().catch((error) => {
        console.error("Failed to load MedAssist widget in full mode", error);
      });
    } else {
      // Show the launcher as soon as its icon is known (host `icon-url` →
      // immediately; otherwise once agent-config resolves — there is no
      // built-in fallback icon), but defer the heavy widget warm-up — fetching
      // the ~220 kB-gzip widget bundle, CSS and nudge data — until the host
      // page is idle so it never competes with the host's own critical
      // resources.
      void this.renderLauncher();
      this.scheduleIdle(() => {
        this.preloadWidgetAssets();
        void this.prefetchAuthTokens();
        this.initNudge();
      });
    }
  }

  disconnectedCallback(): void {
    if (this.placeholderTimer) clearInterval(this.placeholderTimer);
    this.placeholderTimer = null;
    this.reactRoot?.unmount();
    this.reactRoot = null;
    // Defensive final cleanup in case the push callback never fired (e.g. the
    // element was removed from the DOM mid-session) — guarantees no residue
    // is left on the host page.
    document.body?.classList.remove("eka-medassist-pushed");
    document.documentElement?.style.removeProperty("--eka-medassist-panel-width");
    document.documentElement?.style.removeProperty("--eka-medassist-panel-side");
    this.hostPushStyleEl?.remove();
    this.hostPushStyleEl = null;
    this.hostPushState = null;
  }

  /**
   * Side-panel "push" mode: shifts the host page's own <body> aside via a
   * margin injected into the host's real document.head (NOT the shadow root —
   * this must be visible to the host page's own layout). Owns a single style
   * element, toggled via a class on <body> so open/close is just a class flip
   * once the CSS is in place. Fully removes both on revert so closing the
   * widget leaves the host page pixel-identical to before it opened.
   *
   * A body margin only reflows in-flow content sized relative to <body>. Two
   * common host shapes need more, and both are handled here:
   *
   * - App roots sized with `width: 100vw` (Tailwind `w-screen`) resolve against
   *   the viewport, so they ignore the margin and slide under the panel. The
   *   injected `body > * { max-width: 100% }` rule caps body's direct children
   *   at body's (now narrower) content box so they shrink with it. It has no
   *   effect on `position: fixed` children (their containing block is the
   *   viewport) and a host `min-width` still wins over `max-width`.
   * - `position: fixed` host chrome (headers, banners, `inset-0` overlays) is
   *   viewport-anchored and cannot be moved from the outside. The host opts in
   *   via the contract published here: `--eka-medassist-panel-width` /
   *   `--eka-medassist-panel-side` custom properties on <html>, the
   *   `body.eka-medassist-pushed` class, an `eka-medassist:side-panel-push`
   *   window event, and the `EkaMedAssist.onSidePanelPushChange` hook.
   */
  private applyHostPush(isPushed: boolean, widthPx: number, side: "left" | "right"): void {
    if (typeof document === "undefined") return;

    // Idempotent on the (pushed, width, side) tuple so hosts never see a
    // duplicate or spurious signal — the widget bundle is versioned
    // independently of this loader, and React effect re-runs (or a mount
    // that starts closed) can replay the same state.
    const next = isPushed ? { width: widthPx, side } : null;
    const prev = this.hostPushState;
    if (prev === next || (prev && next && prev.width === next.width && prev.side === next.side)) {
      return;
    }
    this.hostPushState = next;

    if (!this.hostPushStyleEl) {
      this.hostPushStyleEl = document.createElement("style");
      this.hostPushStyleEl.setAttribute("data-medassist-side-panel-push", "true");
      document.head.appendChild(this.hostPushStyleEl);
    }

    const marginSide = side === "left" ? "margin-left" : "margin-right";
    this.hostPushStyleEl.textContent = `
      body.eka-medassist-pushed {
        ${marginSide}: ${widthPx}px;
        transition: margin 300ms ease;
      }
      body.eka-medassist-pushed > * {
        max-width: 100%;
      }
      @media (prefers-reduced-motion: reduce) {
        body.eka-medassist-pushed { transition: none !important; }
      }
    `;

    const rootStyle = document.documentElement.style;
    if (isPushed) {
      rootStyle.setProperty("--eka-medassist-panel-width", `${widthPx}px`);
      rootStyle.setProperty("--eka-medassist-panel-side", side);
      document.body.classList.add("eka-medassist-pushed");
    } else {
      document.body.classList.remove("eka-medassist-pushed");
      rootStyle.removeProperty("--eka-medassist-panel-width");
      rootStyle.removeProperty("--eka-medassist-panel-side");
      this.hostPushStyleEl.remove();
      this.hostPushStyleEl = null;
    }

    // Let JS hosts (SPAs that can't express their layout shift in CSS alone)
    // react to the same signal.
    const detail: SidePanelPushDetail = { pushed: isPushed, width: widthPx, side };
    if (typeof window !== "undefined") {
      try {
        window.dispatchEvent(new CustomEvent<SidePanelPushDetail>(SIDE_PANEL_PUSH_EVENT, { detail }));
      } catch {
        // CustomEvent unavailable — nothing to notify
      }
      const hook = (window as EkaMedAssistWindow).EkaMedAssist?.onSidePanelPushChange;
      if (typeof hook === "function") {
        try {
          hook(isPushed, widthPx, side);
        } catch (error) {
          console.error("EkaMedAssist.onSidePanelPushChange threw", error);
        }
      }
    }
  }

  /** Run work when the browser is idle, falling back to a short timeout. */
  private scheduleIdle(work: () => void): void {
    if (typeof window === "undefined") {
      work();
      return;
    }
    const ric = (window as unknown as {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => void;
    }).requestIdleCallback;
    if (typeof ric === "function") {
      ric(work, { timeout: 3000 });
    } else {
      setTimeout(work, 200);
    }
  }

  attributeChangedCallback(name: string): void {
    if (name === "icon-url") {
      if (this.displayMode !== "full") {
        void this.renderLauncher();
      }
    }
    if (name === "display-mode") {
      const newMode = normalizeDisplayMode(this.getAttribute("display-mode"));
      if (newMode !== this.displayMode) {
        this.displayMode = newMode;
        if (newMode === "full") {
          this.initializeFullMode();
        } else {
          void this.renderLauncher();
        }
      }
    }
    if (name === "custom-launcher-styles") {
      this.applyCustomLauncherStyles();
    }
    if (name === "launcher-type") {
      this.updateLauncherView();
    }
  }

  /** When in widget mode, start loading JS and CSS on page load so first open is faster. */
  private preloadWidgetAssets(): void {
    getWidgetCssTextPromise(); // start CSS fetch (no inject until open)
    void this.loadWidgetModule(); // start JS module load (also pre-fetches static chunk imports)
    void this.preloadBackgroundImage();
  }

  private authPrefetchPromise: Promise<PrefetchAuthResult> | null = null;

  /**
   * Kick off the token exchange as soon as the widget module is available so
   * tokens are ready before (or while) the widget opens. Runs in parallel with
   * the agent-config fetch. Safe to call repeatedly — the memoized promise and
   * the core-side prefetch cache both dedupe it; the SDK adopts the in-flight
   * exchange when the widget mounts. The widget-side prefetchAuth skips
   * brand-new anonymous visitors (no partner authToken, no persisted refresh
   * token) so idle pre-warm never mints throwaway guest identities.
   *
   * Returns the exchange result so callers that need the freshly minted sess
   * token (e.g. the nudge request) can read it without the widget ever having
   * been opened — nothing is persisted to the widget store until it mounts.
   */
  private prefetchAuthTokens(): Promise<PrefetchAuthResult> {
    if (this.authPrefetchPromise) return this.authPrefetchPromise;
    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};
    const agentId =
      (initConfig.agentId as string) || this.getAttribute("agent-id") || "";
    if (!agentId) return Promise.resolve(undefined);

    const authToken =
      (initConfig.authToken as string | undefined) ||
      this.getAttribute("auth-token") ||
      undefined;
    const serverUrl =
      (initConfig.baseUrl as string) ||
      this.getAttribute("base-url") ||
      "https://matrix.eka.care/reloaded";
    const environment =
      getEnvironment(this.getAttribute("environment")) ?? "production";

    this.authPrefetchPromise = this.loadWidgetModule()
      .then((module) =>
        module.prefetchAuth?.({
          agentId,
          authToken,
          serverUrl,
          environment,
          channel: this.getChannel(),
        })
      )
      .catch(() => {
        // Non-fatal: the SDK exchanges on open if the prefetch failed. Drop the
        // memo so a later call retries instead of replaying the rejection.
        this.authPrefetchPromise = null;
        return undefined;
      });
    return this.authPrefetchPromise;
  }

  /**
   * Sess (access) token for host-side API calls made before the widget mounts.
   * Prefers the widget store (set once the widget has run in this tab), else
   * the token minted by the idle-time prefetch exchange — which lives only in
   * the in-flight promise until the widget mounts and persists it.
   */
  private async resolveSessToken(agentId: string): Promise<string | undefined> {
    const persisted = readPersistedSessToken(agentId);
    if (persisted) return persisted;
    const exchanged = await this.prefetchAuthTokens();
    return exchanged?.sess_token || readPersistedSessToken(agentId);
  }

  /** Preload theme background image from init config, theme attribute, or agent-config API. */
  private preloadBackgroundImage(): void {
    const initConfig =
      typeof window !== "undefined"
        ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
        : undefined;
    const attributeTheme = this.getAttribute("theme")
      ? (() => {
        try {
          return JSON.parse(this.getAttribute("theme") || "{}") as { backgroundImage?: string };
        } catch {
          return undefined;
        }
      })()
      : undefined;

    const fromInit = initConfig?.theme?.backgroundImage;
    const fromAttr = attributeTheme?.backgroundImage;
    if (fromInit) preloadImage(fromInit);
    if (fromAttr && fromAttr !== fromInit) preloadImage(fromAttr);

    this.getAgentConfig()
      .then((agentConfig) => {
        const url = agentConfig?.theme?.background_img;
        if (url) preloadImage(url);
      })
      .catch(() => {
        // ignore; widget will load config when it opens
      });
  }

  private setupAuthExpirationListener(): void {
    if (typeof window === "undefined") return;

    const messageHandler = (event: MessageEvent) => {
      if (event.data?.type === "AUTH_EXPIRED") {
        if (window.parent !== window) {
          window.parent.postMessage({ type: "AUTH_EXPIRED", message: "Authentication expired" }, "*");
        }
        // window.webkit.messageHandlers.authTokenExpired.postMessage({});
      }
    }

    window.addEventListener("message", messageHandler);
  }

  public openFromBridge(): void {
    this.displayMode = normalizeDisplayMode(this.getAttribute("display-mode"));
    if (this.displayMode === "full") {
      this.initializeFullMode();
    } else {
      void this.renderLauncher();
      // Chatbox launcher: the widget opens only when the user sends from it.
      if (this.getLauncherType() === "chatbox") return;
    }

    this.loadAndRender().catch((error) => {
      console.error("Failed to open MedAssist widget from bridge", error);
    });
  }

  /** Resolve nudge data (from cache or API) and schedule the popup. */
  private async initNudge(): Promise<void> {
    const initConfig =
      typeof window !== "undefined"
        ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
        : undefined;
    const agentId =
      (initConfig?.agentId as string) || this.getAttribute("agent-id") || "";
    if (!agentId) return;

    const resolvedAgentConfig = await this.getAgentConfig();
    if (!resolvedAgentConfig?.nudge) return;

    const nudgeColor = resolvedAgentConfig?.theme?.nudge_color ?? "#ffffff";
    const currentUrl =
      typeof window !== "undefined" ? window.location.href : "";

    let url: URL;
    try {
      url = new URL(currentUrl);
    } catch {
      return;
    }

    // Candidates run from the most specific path back to "/".
    const candidates = getNudgePathCandidates(url.pathname);
    const primaryCandidates = candidates.slice(0, 1); // most specific path
    const fallbackCandidates = candidates.slice(1); // less specific paths

    // 1. Prefer a fresh cached nudge for this exact page. Each visited path
    // gets its own cache entry (storeNudgeResponse also writes one under the
    // visited path when the API matched a broader pattern), so refreshes of a
    // known path skip the API while a never-visited path still asks it — the
    // server may have a more specific pattern for it.
    let hit = findFreshCachedNudge(agentId, url, primaryCandidates);

    // 2. No specific cache hit → ask the API for fresh data.
    if (!hit) {
      const baseUrl =
        (initConfig?.baseUrl as string) ||
        this.getAttribute("base-url") ||
        "https://matrix.eka.care/reloaded";

      // Only block on the token exchange when we actually hit the API — a cache
      // hit above should not wait on it. No token (exchange failed) → skip the
      // API but still fall through to the cached fallback candidates below.
      const sessToken = await this.resolveSessToken(agentId).catch(() => undefined);
      if (sessToken) {
        const response = await fetchNudgeData(agentId, sessToken, baseUrl, this.getChannel()).catch(() => undefined);
        if (response?.nudges?.length) {
          storeNudgeResponse(agentId, response, normalizePath(url.pathname));
          // The API match may land on any candidate path — search them all.
          hit = findFreshCachedNudge(agentId, url, candidates);
        }
      }
    }

    // 3. API returned nothing → fall back to less specific cached candidates.
    if (!hit) {
      hit = findFreshCachedNudge(agentId, url, fallbackCandidates);
    }

    if (!hit) return;

    const nudgeText =
      hit.data.nudges[Math.floor(Math.random() * hit.data.nudges.length)];
    const delaySeconds = hit.data.delay ?? 5;

    setTimeout(() => {
      this.showNudgePopup(nudgeText, nudgeColor);
    }, delaySeconds * 1000);
  }

  private showNudgePopup(text: string, color: string): void {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) return;
    // Don't show nudge if widget is already open
    if (!shadowRoot.getElementById("medassist-widget-root")?.classList.contains("hidden")) return;

    // Skip if user already closed or opened the bot within the last day
    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};
    const agentId = (initConfig.agentId as string) || this.getAttribute("agent-id") || "";
    if (agentId && getNudgeCookie(agentId) !== null) return;

    const existing = shadowRoot.getElementById("medassist-nudge-popup");
    if (existing) return;

    // Position relative to the launcher (chatbox when shown, else the button)
    // so the popup follows it regardless of custom launcher styles (centered,
    // left-aligned, etc.).
    const button = this.isChatboxShown()
      ? shadowRoot.getElementById("medassist-chatbox")
      : shadowRoot.getElementById("medassist-open-btn");
    const buttonRect = button?.getBoundingClientRect();
    const popupWidth = 272;
    const viewportMargin = 12;
    const tailHalfWidth = 8;
    const tailMinOffset = 16;

    const buttonGap = 16;
    let popupLeftPx = window.innerWidth - popupWidth - viewportMargin;
    let popupBottomPx = 76;
    let tailLeftPx = popupWidth - tailMinOffset - tailHalfWidth * 2;

    if (buttonRect && buttonRect.width > 0) {
      const buttonCenterX = buttonRect.left + buttonRect.width / 2;
      const idealLeft = buttonCenterX - popupWidth / 2;
      const maxLeft = window.innerWidth - popupWidth - viewportMargin;
      popupLeftPx = Math.max(viewportMargin, Math.min(idealLeft, maxLeft));
      popupBottomPx = window.innerHeight - buttonRect.top + buttonGap;
      tailLeftPx = Math.max(
        tailMinOffset,
        Math.min(
          buttonCenterX - popupLeftPx - tailHalfWidth,
          popupWidth - tailMinOffset - tailHalfWidth * 2
        )
      );
    }

    const popup = document.createElement("div");
    popup.id = "medassist-nudge-popup";
    popup.innerHTML = `
      <style>
        @keyframes nudge-slide-up {
          from { opacity: 0; transform: translateY(12px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        #medassist-nudge-popup {
          position: fixed;
          bottom: ${popupBottomPx}px;
          left: ${popupLeftPx}px;
          width: ${popupWidth}px;
          background: ${color};
          border-radius: 16px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.14), 0 2px 8px rgba(0,0,0,0.08);
          padding: 16px 16px 14px 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          z-index: 200001;
          animation: nudge-slide-up 0.28s cubic-bezier(0.34,1.56,0.64,1);
          font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
          box-sizing: border-box;
        }
        /* Speech bubble tail pointing down toward the FAB */
        #medassist-nudge-popup::after {
          content: '';
          position: absolute;
          bottom: -8px;
          left: ${tailLeftPx}px;
          width: 16px;
          height: 10px;
          background: ${color};
          clip-path: polygon(0 0, 100% 0, 50% 100%);
        }
        #medassist-nudge-popup {
          cursor: pointer;
        }
        #medassist-nudge-popup:hover {
          box-shadow: 0 10px 36px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.1);
        }
        #medassist-nudge-popup .nudge-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 8px;
        }
        #medassist-nudge-popup .nudge-text {
          font-size: 13.5px;
          line-height: 1.5;
          color: #1a1a1a;
          margin: 0;
          flex: 1;
          font-weight: 400;
          letter-spacing: -0.01em;
        }
        #medassist-nudge-popup .nudge-close {
          flex-shrink: 0;
          width: 22px;
          height: 22px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(0,0,0,0.06);
          border: none;
          border-radius: 50%;
          cursor: pointer;
          font-size: 13px;
          line-height: 1;
          color: #555;
          padding: 0;
          margin-top: -1px;
          transition: background 0.15s;
        }
        #medassist-nudge-popup .nudge-close:hover {
          background: rgba(0,0,0,0.18);
        }
      </style>
      <div class="nudge-header">
        <p class="nudge-text">${text.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</p>
        <button class="nudge-close" aria-label="Dismiss">&#x2715;</button>
      </div>
    `;

    popup.querySelector(".nudge-close")?.addEventListener("click", (e) => {
      e.stopPropagation();
      if (agentId) setNudgeCookie(agentId, "closed");
      this.dismissNudgePopup();
    });

    popup.addEventListener("click", () => {
      if (agentId) setNudgeCookie(agentId, "closed");
      this.dismissNudgePopup();
      // Chatbox launcher: the session starts on send, so just hand over the focus.
      if (this.isChatboxShown()) {
        (shadowRoot.getElementById("medassist-chatbox-input") as HTMLInputElement | null)?.focus();
        return;
      }
      this.loadAndRender();
    });

    shadowRoot.appendChild(popup);
  }

  private dismissNudgePopup(): void {
    const popup = this.shadowRoot?.getElementById("medassist-nudge-popup");
    popup?.remove();
  }

  private applyCustomLauncherStyles(): void {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) return;
    if (this.displayMode === "full") return;

    // Two layers over the built-in defaults, later wins: agent-config
    // `theme.launcher_styles`, then the host's `custom-launcher-styles`.
    const agentId = this.getAgentId();
    const configCss = (agentId ? readAgentConfigCache(agentId)?.theme?.launcher_styles : undefined) ?? "";
    this.setLauncherStyleTag("data-medassist-config-launcher", configCss);

    const existing = shadowRoot.querySelector<HTMLStyleElement>(
      'style[data-medassist-custom-launcher="true"]'
    );
    const css = this.getAttribute("custom-launcher-styles") ?? "";

    if (!css) {
      existing?.remove();
      return;
    }

    if (existing) {
      existing.textContent = css;
      return;
    }

    const styleEl = document.createElement("style");
    styleEl.setAttribute("data-medassist-custom-launcher", "true");
    styleEl.textContent = css;
    shadowRoot.appendChild(styleEl);
  }

  /** Agent-config launcher CSS tag, kept before the host's tag so the host's rules win. */
  private setLauncherStyleTag(attribute: string, css: string): void {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) return;
    const existing = shadowRoot.querySelector<HTMLStyleElement>(`style[${attribute}="true"]`);
    if (!css) {
      existing?.remove();
      return;
    }
    if (existing) {
      existing.textContent = css;
      return;
    }
    const styleEl = document.createElement("style");
    styleEl.setAttribute(attribute, "true");
    styleEl.textContent = css;
    const hostStyle = shadowRoot.querySelector('style[data-medassist-custom-launcher="true"]');
    shadowRoot.insertBefore(styleEl, hostStyle);
  }

  /** Agent id from init() or the attribute — the same precedence as everywhere else in this loader. */
  private getAgentId(): string {
    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};
    return (initConfig.agentId as string) || this.getAttribute("agent-id") || "";
  }

  /** Bumped on every renderLauncher() call so an older, still-awaiting resolution never overwrites a newer one. */
  private launcherRenderSeq = 0;

  /**
   * Render the launcher skeleton now and reveal it once its icon is known:
   *   1. host-supplied `icon-url` (attribute or init({ iconUrl })) → shown now;
   *   2. otherwise agent-config `theme.icon_img` — a cached copy shows at once
   *      and is refreshed at idle; with no cache the launcher stays hidden
   *      until the fetch resolves.
   * There is deliberately no built-in fallback icon, so a host never sees a
   * generic icon flash before their own appears. If neither source yields an
   * icon the launcher is still revealed (the chat must stay reachable), just
   * without an image.
   */
  private async renderLauncher(): Promise<void> {
    if (this.displayMode === "full") return;
    const seq = ++this.launcherRenderSeq;

    // The skeleton (hidden launcher + widget root) must exist synchronously:
    // init() may open the widget via openFromBridge before any icon resolves.
    this.renderButton();

    const hostIconUrl = this.getAttribute("icon-url");
    if (hostIconUrl) {
      this.setLauncherIcon(hostIconUrl);
      // The icon needs no config, but the launcher type and styles may come
      // from it — refresh the cache at idle and re-apply.
      const hostAgentId = this.getAgentId();
      if (hostAgentId) {
        this.scheduleIdle(() => {
          void this.getAgentConfig().then((fresh) => {
            if (!fresh || seq !== this.launcherRenderSeq) return;
            writeAgentConfigCache(hostAgentId, fresh);
            this.updateLauncherView();
          });
        });
      }
      return;
    }

    // No agent yet (init({ agentId }) not called) → nothing to resolve against;
    // init() re-enters here via openFromBridge once the id is known.
    const agentId = this.getAgentId();
    if (!agentId) return;

    const cachedIcon = readAgentConfigCache(agentId)?.theme?.icon_img;
    if (cachedIcon) {
      this.setLauncherIcon(cachedIcon);
    }

    const applyFresh = async () => {
      const fresh = await this.getAgentConfig().catch(() => undefined);
      // Superseded (icon-url set by init(), display-mode flipped) — drop it.
      if (seq !== this.launcherRenderSeq) return;
      if (fresh) writeAgentConfigCache(agentId, fresh);
      this.setLauncherIcon(fresh?.theme?.icon_img || cachedIcon);
    };

    if (cachedIcon) {
      // Already showing the cached icon — keep the bundle download (which the
      // config fetch rides on) out of the host's critical path.
      this.scheduleIdle(() => { void applyFresh(); });
    } else {
      await applyFresh();
    }
  }

  /** Set (or clear) the launcher image and reveal the launcher. */
  private setLauncherIcon(iconUrl: string | undefined): void {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) return;
    const img = shadowRoot.querySelector<HTMLImageElement>("#medassist-open-btn img");
    if (img) {
      if (iconUrl) {
        img.src = iconUrl;
      } else {
        img.removeAttribute("src");
      }
    }
    shadowRoot.getElementById("medassist-open-btn")?.classList.remove("pending");
    shadowRoot.getElementById("medassist-chatbox")?.classList.remove("pending");
    this.updateLauncherView();
  }

  /**
   * Chatbox colours, with the same precedence the widget's theme uses:
   * init({ theme }), then the `theme` attribute, then agent-config (cached)
   * `accent` / `mode`. Nothing usable (no config yet, fetch failed) → the CSS
   * fallbacks, which are the widget's own defaults.
   */
  private applyChatboxTheme(chatbox: HTMLElement): void {
    const initTheme = ((typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {}).theme;
    let attributeTheme: MedAssistInitConfig["theme"];
    try {
      attributeTheme = JSON.parse(this.getAttribute("theme") || "{}");
    } catch {
      attributeTheme = undefined;
    }
    const agentId = this.getAgentId();
    const configTheme = agentId ? readAgentConfigCache(agentId)?.theme : undefined;

    const accent = initTheme?.primary || attributeTheme?.primary || configTheme?.accent;
    if (accent) {
      chatbox.style.setProperty("--medassist-chatbox-accent", accent);
      chatbox.style.setProperty("--medassist-chatbox-on-accent", colorOnAccent(accent));
    }
    const mode = initTheme?.mode || attributeTheme?.mode || configTheme?.mode;
    if (mode === "dark") {
      chatbox.setAttribute("data-mode", "dark");
    } else {
      chatbox.removeAttribute("data-mode");
    }
  }


  /**
   * Render the launcher skeleton (idempotent). The launcher starts `pending`
   * (not displayed) and is revealed by setLauncherIcon() once renderLauncher()
   * has decided which icon it carries — see that method for the order.
   */
  renderButton(): void {
    const shadowRoot = this.shadowRoot;

    if (!shadowRoot) {
      console.error("Shadow root was not created");
      return;
    }

    if (!shadowRoot.querySelector("button")) {
      shadowRoot.innerHTML = `
        <style>
          #medassist-open-btn {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            border: none;
            cursor: pointer;
            background-color:rgb(255, 255, 255);
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
          }
          #medassist-open-btn img {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            object-fit: cover;
          }
          /* No icon from the host or agent-config: keep the launcher clickable
             but never show a broken-image glyph. */
          #medassist-open-btn img:not([src]) {
            display: none;
          }
          /* Icon not resolved yet (waiting on agent-config): nothing is shown —
             there is no default icon to fall back to. */
          #medassist-open-btn.pending {
            display: none !important;
          }
          :host {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 200000;
          }
          #medassist-open-btn:hover {
            background-color:rgb(239, 237, 245);
          }
          .hidden {
            display: none !important;
          }
          #medassist-open-btn.hidden {
            display: none !important;
          }
          /* Loading state: the launcher stays exactly where it is (so custom
             launcher styles still apply) and swaps its icon for a spinner
             while the widget bundle + config are fetched. */
          #medassist-open-btn.loading {
            cursor: default;
            pointer-events: none;
          }
          #medassist-open-btn.loading img {
            display: none;
          }
          #medassist-loader {
            display: none;
            width: 26px;
            height: 26px;
            box-sizing: border-box;
            border-radius: 50%;
            border: 3px solid rgba(0, 0, 0, 0.12);
            border-top-color: rgba(0, 0, 0, 0.45);
            animation: medassist-spin 0.7s linear infinite;
          }
          #medassist-open-btn.loading #medassist-loader {
            display: block;
          }
          @keyframes medassist-spin {
            to { transform: rotate(360deg); }
          }
          @media (prefers-reduced-motion: reduce) {
            #medassist-loader {
              animation-duration: 1.8s;
            }
          }
          /* Chatbox launcher (launcher-type="chatbox"). Defaults only — agent
             config launcher_styles and the host's custom-launcher-styles are
             applied after this and win. */
          /* Looks like the widget's floating composer (ChatComposer): card on
             --elicitation-bg, 1px accent border at 30%, 20px radius, round accent
             send button. Colours come from the agent-config theme (accent, mode)
             via the variables set in updateLauncherView(); the fallbacks here
             are the widget's own defaults (#6B5CE0, light mode). */
          #medassist-chatbox {
            --medassist-chatbox-accent: #6B5CE0;
            --medassist-chatbox-on-accent: #fafafa;
            --medassist-chatbox-bg: #ffffff;
            --medassist-chatbox-text: #000000;
            --medassist-chatbox-placeholder: #8c8c8c;
            /* Bottom centre. A host moving it to a corner must also reset
               left and translate, e.g. left: auto; right: 20px; translate: none. */
            position: fixed;
            bottom: 20px;
            left: 50%;
            right: auto;
            translate: -50% 0;
            /* 40% of the page, but never narrower than 420px. */
            width: 360px;
            max-width: calc(100vw - 32px);
            box-sizing: border-box;
            display: flex;
            align-items: flex-end;
            gap: 8px;
            margin: 0;
            min-height: 48px;
            padding: 7px 7px 7px 20px;
            background: var(--medassist-chatbox-bg);
            border: 1px solid rgba(107, 92, 224, 0.3);
            border: 1px solid color-mix(in srgb, var(--medassist-chatbox-accent) 30%, transparent);
            border-radius: 24px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08), 0 12px 32px rgba(0, 0, 0, 0.22), 0 28px 64px -8px rgba(0, 0, 0, 0.28);
            transition: scale 200ms cubic-bezier(0.32, 0.72, 0, 1), box-shadow 200ms ease, border-color 200ms ease;
            font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          #medassist-chatbox[data-mode="dark"] {
            --medassist-chatbox-bg: #000000;
            --medassist-chatbox-text: #ffffff;
            --medassist-chatbox-placeholder: #808080;
          }
          #medassist-chatbox.pending {
            display: none !important;
          }
          /* Invitation pulse: while the bar is idle and untouched (nothing typed),
             one accent wave ripples out from its edge, then
             rests ~4s before the next. Pseudo-elements, so the bar's own shadow,
             hover scale and centring are untouched. Managed from JS
             (syncChatboxPulse): off once the user types, a chat is in progress,
             or reduced motion is on. */
          #medassist-chatbox.pulse::before {
            content: "";
            position: absolute;
            left: -1px;
            top: -1px;
            right: -1px;
            bottom: -1px;
            border-radius: inherit;
            pointer-events: none;
            animation: medassist-chatbox-ripple 5.5s ease-out infinite;
          }
          #medassist-chatbox.pulse::before {
            --medassist-ripple: color-mix(in srgb, var(--medassist-chatbox-accent) 38%, transparent);
          }
          @keyframes medassist-chatbox-ripple {
            0% { box-shadow: 0 0 0 0 var(--medassist-ripple); }
            22% { box-shadow: 0 0 0 16px transparent; }
            100% { box-shadow: 0 0 0 16px transparent; }
          }
          /* A textarea so a long message wraps and the bar grows upward (it is
             anchored at the bottom). Single line = 32px: 6px padding around one
             20px line. Capped at 4 lines (92px); beyond that it scrolls. */
          #medassist-chatbox-input {
            flex: 1;
            min-width: 0;
            display: block;
            box-sizing: border-box;
            height: 32px;
            min-height: 32px;
            max-height: 92px;
            margin: 0;
            padding: 6px 0;
            border: none;
            outline: none;
            resize: none;
            overflow-y: hidden;
            background: transparent;
            color: var(--medassist-chatbox-text);
            font-size: 15px;
            line-height: 20px;
            font-family: inherit;
          }
          /* Minimal scrollbar, only visible once the text is taller than 4 lines. */
          #medassist-chatbox-input::-webkit-scrollbar { width: 4px; }
          #medassist-chatbox-input::-webkit-scrollbar-track { background: transparent; margin: 8px 0; }
          #medassist-chatbox-input::-webkit-scrollbar-thumb {
            background: color-mix(in srgb, var(--medassist-chatbox-text) 22%, transparent);
            border-radius: 2px;
          }
          #medassist-chatbox-input::-webkit-scrollbar-thumb:hover {
            background: color-mix(in srgb, var(--medassist-chatbox-accent) 55%, transparent);
          }
          @supports not selector(::-webkit-scrollbar) {
            #medassist-chatbox-input {
              scrollbar-width: thin;
              scrollbar-color: color-mix(in srgb, var(--medassist-chatbox-text) 22%, transparent) transparent;
            }
          }
          /* Soft fade at the edge(s) the text is scrolled past, so it never cuts off sharply. */
          #medassist-chatbox-input.fade-t {
            -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 16px);
            mask-image: linear-gradient(to bottom, transparent 0, #000 16px);
          }
          #medassist-chatbox-input.fade-b {
            -webkit-mask-image: linear-gradient(to top, transparent 0, #000 16px);
            mask-image: linear-gradient(to top, transparent 0, #000 16px);
          }
          #medassist-chatbox-input.fade-t.fade-b {
            -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 16px, #000 calc(100% - 16px), transparent 100%);
            mask-image: linear-gradient(to bottom, transparent 0, #000 16px, #000 calc(100% - 16px), transparent 100%);
          }
          #medassist-chatbox-input::placeholder {
            color: var(--medassist-chatbox-placeholder);
          }
          #medassist-chatbox.sending #medassist-chatbox-input {
            opacity: 0.6;
          }
          .medassist-chatbox-send {
            flex-shrink: 0;
            width: 32px;
            height: 32px;
            border: none;
            border-radius: 50%;
            padding: 0;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--medassist-chatbox-accent);
            color: var(--medassist-chatbox-on-accent);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
            transition: transform 200ms, box-shadow 200ms;
          }
          .medassist-chatbox-send:hover {
            transform: scale(1.05);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
          }
          .medassist-chatbox-send:active {
            transform: scale(0.95);
          }
          .medassist-chatbox-send:disabled {
            opacity: 0.4;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
          }
          .medassist-chatbox-send svg {
            width: 14px;
            height: 14px;
          }
          .medassist-chatbox-spinner {
            display: none;
            width: 18px;
            height: 18px;
            box-sizing: border-box;
            border-radius: 50%;
            border: 2px solid currentColor;
            border-top-color: transparent;
            animation: medassist-spin 0.7s linear infinite;
          }
          #medassist-chatbox.sending .medassist-chatbox-send {
            cursor: default;
            pointer-events: none;
          }
          #medassist-chatbox.sending .medassist-chatbox-send svg {
            display: none;
          }
          #medassist-chatbox.sending .medassist-chatbox-spinner {
            display: block;
          }
          /* Hover (mouse only): the whole bar grows 2% — the individual \`scale\`
             property, so it composes with a host's own transform override. */
          @media (hover: hover) and (pointer: fine) {
            #medassist-chatbox:hover:not(.sending):not(.pending) {
              scale: 1.02;
              border-color: color-mix(in srgb, var(--medassist-chatbox-accent) 55%, transparent);
              box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1), 0 16px 40px rgba(0, 0, 0, 0.26), 0 32px 72px -8px rgba(0, 0, 0, 0.3);
            }
          }
          /* Rotating placeholder: a text layer over the input, so it can slide. */
          .medassist-chatbox-field {
            position: relative;
            flex: 1;
            min-width: 0;
            min-height: 32px;
            display: flex;
            align-items: flex-start;
          }
          .medassist-chatbox-field #medassist-chatbox-input {
            width: 100%;
          }
          #medassist-chatbox-ph {
            position: absolute;
            left: 0;
            top: 0;
            max-width: 100%;
            height: 32px;
            line-height: 32px;
            font-size: 15px;
            color: var(--medassist-chatbox-placeholder);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            pointer-events: none;
            transition: opacity 220ms ease, transform 220ms ease;
          }
          #medassist-chatbox-ph.out { opacity: 0; transform: translateY(-8px); }
          #medassist-chatbox-ph.in { opacity: 0; transform: translateY(8px); transition: none; }
          #medassist-chatbox-ph.gone { display: none; }
          /* Widget closed with a chat in progress: any click reopens it. */
          #medassist-chatbox.continuing { cursor: pointer; }
          #medassist-chatbox.continuing #medassist-chatbox-input { cursor: pointer; }
          @media (prefers-reduced-motion: reduce) {
            #medassist-chatbox, #medassist-chatbox-ph { transition: none; }
          }
          @media (max-width: 768px) {
            #medassist-chatbox {
              left: 16px;
              right: 16px;
              bottom: calc(16px + env(safe-area-inset-bottom, 0px));
              min-height: 52px;
              padding: 7px 7px 7px 18px;
              border-radius: 26px;
              transform: none;
              translate: none;
              width: auto;
              max-width: none;
            }
            .medassist-chatbox-field { min-height: 36px; }
            #medassist-chatbox-input {
              height: 36px;
              min-height: 36px;
              max-height: 96px;
              padding: 8px 0;
              font-size: 16px;
            }
            #medassist-chatbox-ph {
              height: 36px;
              line-height: 36px;
              font-size: 16px;
            }
            .medassist-chatbox-send {
              width: 36px;
              height: 36px;
            }
          }
        </style>

        <button id="medassist-open-btn" class="pending" aria-label="Open MedAssist">
          <img alt="MedAssist Icon">
          <span id="medassist-loader" aria-hidden="true"></span>
        </button>
        <form id="medassist-chatbox" class="pending hidden" autocomplete="off" novalidate>
          <div class="medassist-chatbox-field">
            <textarea id="medassist-chatbox-input" rows="1" enterkeyhint="send" maxlength="2000" aria-label="Message MedAssist"></textarea>
            <span id="medassist-chatbox-ph" aria-hidden="true"></span>
          </div>
          <button type="submit" class="medassist-chatbox-send" aria-label="Send message" disabled>
            <svg viewBox="0 0 17 16" fill="none" aria-hidden="true"><path d="M1.46875 0.09375L16.3125 6.9375C16.75 7.125 17 7.53125 17 8C17 8.46875 16.75 8.875 16.3125 9.0625L1.46875 15.9062C1.3125 15.9688 1.1875 16 1.03125 16C0.46875 16 0 15.5312 0 14.9688C0 14.8125 0.03125 14.6875 0.09375 14.5625L2.34375 9.5C2.5 9.15625 2.8125 8.9375 3.15625 8.90625L8.0625 8.46875C8.3125 8.46875 8.5 8.25 8.5 8C8.5 7.75 8.3125 7.5625 8.0625 7.53125L3.15625 7.09375C2.8125 7.0625 2.5 6.84375 2.34375 6.5L0.09375 1.4375C0.03125 1.3125 0 1.1875 0 1.03125C0 0.46875 0.46875 0 1.03125 0C1.1875 0 1.3125 0.03125 1.46875 0.09375Z" fill="currentColor"/></svg>
            <span class="medassist-chatbox-spinner" aria-hidden="true"></span>
          </button>
        </form>
        <div id="medassist-widget-root" class="hidden"></div>
      `;

      shadowRoot
        .getElementById("medassist-open-btn")
        ?.addEventListener("click", () => {
          const aid = this.getAgentId();
          if (aid) setNudgeCookie(aid, "closed");
          this.dismissNudgePopup();
          this.loadAndRender();
        });

      const chatboxInput = shadowRoot.getElementById("medassist-chatbox-input") as HTMLInputElement | null;
      let warmedUp = false;
      const chatboxSend = shadowRoot.querySelector<HTMLButtonElement>(".medassist-chatbox-send");
      chatboxInput?.addEventListener("input", () => {
        // Nothing typed (or only spaces): nothing to send.
        if (chatboxSend) chatboxSend.disabled = !chatboxInput.value.trim();
        this.syncChatboxPlaceholder();
        this.syncChatboxPulse();
        this.autosizeChatbox();
        if (warmedUp) return;
        warmedUp = true;
        // First keystroke: fetch the bundle, CSS and auth tokens now so the
        // widget opens fast on send. No session starts until then.
        this.preloadWidgetAssets();
        void this.prefetchAuthTokens();
      });

      const chatboxForm = shadowRoot.getElementById("medassist-chatbox");
      // The invitation pulse is driven by syncChatboxPulse(): it runs for as long as nothing has been typed.

      // Widget closed with a chat in progress: a click anywhere on the bar, or
      // Enter on it, reopens the widget from the centre. No message needed.
      const reopen = () => {
        if (!this.chatStarted || this.loading || this.launcherState !== "idle") return false;
        const aid = this.getAgentId();
        if (aid) setNudgeCookie(aid, "closed");
        this.dismissNudgePopup();
        void this.loadAndRender();
        return true;
      };
      chatboxForm?.addEventListener("click", (event) => {
        if (reopen()) event.preventDefault();
      });
      chatboxInput?.addEventListener("scroll", () => this.updateChatboxFades());
      // Enter sends (or reopens); Shift+Enter adds a line.
      chatboxInput?.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        if (reopen()) return;
        if (chatboxInput.value.trim()) (chatboxForm as HTMLFormElement | null)?.requestSubmit();
      });
      this.startPlaceholderRotation();

      chatboxForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = chatboxInput?.value.trim();
        if (!text && reopen()) return;
        if (!text || this.loading) return;
        const aid = this.getAgentId();
        if (aid) setNudgeCookie(aid, "closed");
        this.dismissNudgePopup();
        void this.loadAndRender(text);
      });
    }

    this.applyCustomLauncherStyles();
  }

  initializeFullMode(): void {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) {
      console.error("Shadow root is not available");
      return;
    }

    if (!shadowRoot.getElementById("medassist-widget-root")) {
      shadowRoot.innerHTML = `
        <style>
         :host {
         display: block;
         width: 100%;
         height: 100%;
         position: fixed;
         top: 0;
         left: 0;
         z-index: 200000;
         }
           #medassist-widget-root {
            width: 100%;
            height: 100%;
          }
        </style>
        <div id="medassist-widget-root"></div>
      `;
    }
  }

  /** `firstUserMessage`: text sent from the chatbox launcher; the widget sends it once connected. */
  async loadAndRender(firstUserMessage?: string): Promise<void> {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) {
      console.error("Shadow root is not available");
      return;
    }

    // The launcher stays visible (as a spinner) while loading, so guard against
    // a second click kicking off a parallel load.
    if (this.loading) return;

    // Start the token exchange in parallel with the config fetch and asset
    // load below (no-op when the idle pre-warm already ran it).
    void this.prefetchAuthTokens();

    // Reset host visibility in case it was hidden by a previous close in full mode
    this.style.display = "";

    const rootElement = shadowRoot.getElementById("medassist-widget-root");
    const agentId = this.getAttribute("agent-id");
    let iconUrl: string | undefined = this.getAttribute("icon-url") || undefined;
    const environment =
      getEnvironment(this.getAttribute("environment")) ?? "production";
    const connectionTypeAttr = this.getAttribute("connectivity");
    const attrConnectionType =
      connectionTypeAttr === "http_stream" || connectionTypeAttr === "socket"
        ? connectionTypeAttr
        : undefined;
    // Opt-in clean start: wipes every persisted credential/session for this
    // agent before the widget hydrates, forcing a fresh login.
    const force = this.getAttribute("force-start") === "true";
    let title = this.getAttribute("title") || "Medi Clinic";
    const baseUrl = this.getAttribute("base-url") || "https://matrix.eka.care/reloaded";
    const displayModeAttribute = this.getAttribute("display-mode");
    const displayMode: "full" | "widget" | "side_panel" = normalizeDisplayMode(displayModeAttribute);
    const attributeContext = this.getAttribute("context") ? JSON.parse(this.getAttribute("context") || "{}") : undefined;
    const attributeTheme = this.getAttribute("theme") ? (() => { try { return JSON.parse(this.getAttribute("theme") || "{}"); } catch { return undefined; } })() : undefined;
    const attributeFeedback: AgentConfig["feedback"] | undefined = this.getAttribute("feedback")
      ? (() => { try { return JSON.parse(this.getAttribute("feedback") || "{}") as AgentConfig["feedback"]; } catch { return undefined; } })()
      : undefined;

    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};

    const attrSidePanelMode = this.getAttribute("side-panel-mode");
    const sidePanelMode: "push" | "overlay" =
      (initConfig.sidePanelMode as "push" | "overlay" | undefined) ||
      (attrSidePanelMode === "overlay" ? "overlay" : "push");
    const attrSidePanelWidth = this.getAttribute("side-panel-width");
    const sidePanelWidth =
      (initConfig.sidePanelWidth as number | undefined) ??
      (attrSidePanelWidth ? Number(attrSidePanelWidth) : undefined);
    const side: "left" | "right" =
      (initConfig.side as "left" | "right" | undefined) ||
      (this.getAttribute("side") as "left" | "right" | null) ||
      (typeof document !== "undefined" && document.dir === "rtl" ? "left" : "right");

    // Host size attributes (floating mode only). Only finite numbers > 0 are
    // forwarded; the widget resolves precedence and clamps (resolveWidgetSize).
    const positiveNumberAttr = (name: string): number | undefined => {
      const value = Number(this.getAttribute(name));
      return Number.isFinite(value) && value > 0 ? value : undefined;
    };
    const overrideWidgetWidth = positiveNumberAttr("override-widget-width");
    const overrideWidgetHeight = positiveNumberAttr("override-widget-height");
    const attributeWidgetSize = {
      ...(overrideWidgetWidth !== undefined && { overrideWidgetWidth }),
      ...(overrideWidgetHeight !== undefined && { overrideWidgetHeight }),
    };

    const mergedContext = {
      ...(attributeContext || {}),
      ...(initConfig.context || {}),
    };

    const authToken =
      (initConfig.authToken as string | undefined) ||
      this.getAttribute("auth-token") ||
      undefined;
    const resolvedAgentId = initConfig.agentId || agentId;
    const apiBaseUrl = (initConfig.baseUrl as string) || baseUrl;

    const customOnClose = typeof window !== "undefined" ? (window as EkaMedAssistWindow).EkaMedAssist?.onClose : undefined;

    const attrRedirectUrl = this.getAttribute("redirect-url") || undefined;
    const redirectUrl = (initConfig.redirectUrl as string | undefined) || attrRedirectUrl;
    const showCloseButton = !!redirectUrl || initConfig.showCloseButton === true;

    if (!resolvedAgentId) {
      console.error("Agent ID is required");
      return;
    }

    if (!rootElement) {
      console.error("Widget root element is missing");
      return;
    }

    // Show the spinner in the launcher's place until the widget is mounted —
    // the config fetch and bundle download below can take a moment.
    this.loading = true;
    this.setLauncherState("loading");
    rootElement.classList.remove("hidden");

    // Fetch agent-config: use localStorage cache for instant startup, refresh in background.
    let apiTheme: MedAssistInitConfig["theme"] = undefined;
    let allowed: ("text" | "file" | "audio" | "voice")[] | undefined;
    let configConnectivity: "http_stream" | "socket" | undefined;
    let resize: boolean = false;
    let initialMessage: AgentConfig["initial_message"] = undefined;
    let hideWatermark: boolean = false;
    let feedback: AgentConfig["feedback"] = undefined;

    const applyAgentConfig = (agentConfig: AgentConfig) => {
      title = agentConfig.name || title;
      iconUrl = agentConfig.theme?.icon_img || iconUrl;
      apiTheme = mapAgentConfigThemeToWidgetTheme(agentConfig.theme || undefined);
      allowed = agentConfig.allowed;
      configConnectivity = agentConfig.connectivity;
      resize = agentConfig.resize || initConfig?.resize || false;
      initialMessage = agentConfig.initial_message;
      hideWatermark = agentConfig.theme?.hide_watermark ?? false;
      feedback = agentConfig.feedback;
    };

    const cachedConfig = readAgentConfigCache(resolvedAgentId);
    if (cachedConfig) {
      applyAgentConfig(cachedConfig);
      // Refresh cache in the background without blocking render
      this.getAgentConfig()
        .then((fresh) => { if (fresh) writeAgentConfigCache(resolvedAgentId, fresh); })
        .catch(() => { });
    } else {
      try {
        const agentConfig = await this.getAgentConfig();
        if (agentConfig) {
          writeAgentConfigCache(resolvedAgentId, agentConfig);
          applyAgentConfig(agentConfig);
        }
      } catch {
        // ignore; use attribute + init theme only
      }
    }

    const connectionType: "http_stream" | "socket" =
      attrConnectionType || configConnectivity || "socket";

    const widgetConfig = {
      title: (initConfig.title as string) || title,
      iconUrl: iconUrl || (initConfig.iconUrl as string | undefined),
      showCloseButton,
      allowed,
      environment,
      connectionType,
      onClose: () => {
        // Unmount the React root so all effect cleanups (e.g. body scroll lock) run immediately
        this.reactRoot?.unmount();
        this.reactRoot = null;
        if (customOnClose && typeof customOnClose === "function") {
          customOnClose();
        }
        if (redirectUrl) {
          window.location.href = redirectUrl;
          return;
        }
        if (displayMode === "full") {
          // In full mode the :host is position:fixed covering the entire viewport.
          // Hiding only the inner rootElement leaves the host element blocking all
          // pointer events on the page. Hide the host itself instead.
          this.style.display = "none";
        } else {
          this.setLauncherState("idle");
          rootElement.classList.add("hidden");
        }
      },
      baseUrl: apiBaseUrl,
      context: mergedContext,
      displayMode,
      sidePanelMode,
      sidePanelWidth,
      side,
      onSidePanelPushChange: (isPushed: boolean, widthPx: number, pushSide: "left" | "right") =>
        this.applyHostPush(isPushed, widthPx, pushSide),
      resize: resize || (this.getAttribute("resize") === "true" ? true : false),
      authToken,
      force,
      initialMessage,
      hideWatermark,
      ...((attributeFeedback || feedback) && { feedback: attributeFeedback || feedback }),
      ...(firstUserMessage && { firstUserMessage }),
      theme: {
        // Chatbox launcher: a wider window by default (520px). Agent-config widget_width and the host's override still win.
        ...(this.isChatboxShown() && { widgetWidth: 520 }),
        ...(apiTheme || {}),
        ...(attributeTheme || {}),
        ...attributeWidgetSize,
        ...(initConfig.theme || {}),
        // Chatbox launcher: the window opens bottom-centre, where the chatbox sits, not in the corner.
        ...(this.isChatboxShown() && { openFrom: "bottom-center" as const }),
      }
    };

    const w = window as EkaMedAssistWindow;

    // Opened from the chatbox (send, or a click while a chat is in progress): remember where it sits so the window can grow out of it.
    const chatboxRect = this.isChatboxShown()
      ? shadowRoot.getElementById("medassist-chatbox")?.getBoundingClientRect()
      : undefined;

    if (this.widgetLoaded) {
      this.reactRoot = w.renderMedAssist!(rootElement, resolvedAgentId, widgetConfig);
      this.chatStarted = true;
      if (chatboxRect) await this.growWidgetFromChatbox(chatboxRect);
      this.setLauncherState("open");
      this.loading = false;
      return;
    }

    try {
      const [, widgetModule] = await Promise.all([this.loadWidgetCss(), this.loadWidgetModule()]);
      this.reactRoot = widgetModule.renderMedAssist(rootElement, resolvedAgentId, widgetConfig);
      this.widgetLoaded = true;
      this.chatStarted = true;
      if (chatboxRect) await this.growWidgetFromChatbox(chatboxRect);
      this.setLauncherState("open");
    } catch (error) {
      console.error("Failed to load MedAssist widget", error);
      // Restore the launcher so the user can retry.
      this.setLauncherState("idle");
      rootElement.classList.add("hidden");
    } finally {
      this.loading = false;
    }
  }

  /** Opening animation: `open-animation` attribute / init({ openAnimation }): rise (default) | unfold | pop | curtain | fade | none. */
  private getOpenAnimation(): "unfold" | "rise" | "pop" | "curtain" | "fade" | "none" {
    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};
    const value = this.getAttribute("open-animation") || (initConfig as { openAnimation?: string }).openAnimation;
    return value === "unfold" || value === "pop" || value === "curtain" || value === "fade" || value === "none" ? value : "rise";
  }

  /**
   * Chatbox → widget opening animation. The window sits bottom-centre, exactly
   * where the chatbox is. Style is chosen with `open-animation`:
   * - rise (default): lifts up from just below with a soft fade
   * - unfold: starts as the chatbox pill and unfolds upward/outward
   * - pop: springs out of the bar with a small overshoot
   * - curtain: a full-width wipe from the bottom edge upward
   * - fade: a plain, quick crossfade
   * - none: no animation
   * Content settles in a beat after the shape (except fade). Resolves once the
   * animation has started; never throws — worst case the widget just appears.
   */
  private async growWidgetFromChatbox(from: DOMRect): Promise<void> {
    try {
      const kind = this.getOpenAnimation();
      if (kind === "none" || prefersReducedMotion()) return;
      const shadowRoot = this.shadowRoot;
      // React commits asynchronously: wait (a few frames at most) for the window.
      let container: HTMLElement | null = null;
      for (let frame = 0; frame < 30 && !container; frame++) {
        await nextFrame();
        container = shadowRoot?.querySelector<HTMLElement>(".synapse-chat-widget-container") ?? null;
      }
      if (!container || typeof container.animate !== "function") return;
      const to = container.getBoundingClientRect();
      if (!to.width || !to.height || !from.width) return;

      // Edge-to-edge (mobile) ends square; the floating window has 24px corners.
      const endRadius = to.width >= window.innerWidth - 1 ? 0 : 24;
      const origin = "50% 100%";

      if (kind === "rise") {
        container.animate(
          [
            { transform: "translateY(56px) scale(0.96)", opacity: 0, transformOrigin: origin },
            { transform: "translateY(0px) scale(1)", opacity: 1, transformOrigin: origin },
          ],
          { duration: 520, easing: "cubic-bezier(0.22, 1, 0.36, 1)" }
        );
      } else if (kind === "pop") {
        container.animate(
          [
            { transform: "scale(0.4)", opacity: 0, transformOrigin: origin },
            { transform: "scale(1.04)", opacity: 1, transformOrigin: origin, offset: 0.6 },
            { transform: "scale(1)", opacity: 1, transformOrigin: origin },
          ],
          { duration: 560, easing: "cubic-bezier(0.34, 1.2, 0.64, 1)" }
        );
      } else if (kind === "curtain") {
        container.animate(
          [
            { transform: "translateY(20px)", clipPath: `inset(100% 0px 0px 0px round ${endRadius}px)` },
            { transform: "translateY(0px)", clipPath: `inset(0px 0px 0px 0px round ${endRadius}px)` },
          ],
          { duration: 560, easing: "cubic-bezier(0.65, 0, 0.35, 1)" }
        );
      } else if (kind === "fade") {
        container.animate(
          [
            { transform: "scale(0.97)", opacity: 0, transformOrigin: origin },
            { transform: "scale(1)", opacity: 1, transformOrigin: origin },
          ],
          { duration: 280, easing: "ease-out" }
        );
        return;
      } else {
        // unfold: start as the chatbox pill (same spot and size, clipped to it).
        const dx = from.left + from.width / 2 - (to.left + to.width / 2);
        const dy = from.bottom - to.bottom;
        const insetTop = Math.max(0, to.height - from.height);
        const insetSide = Math.max(0, (to.width - from.width) / 2);
        const startRadius = Math.min(from.height / 2, 28);
        container.animate(
          [
            {
              transform: `translate(${dx}px, ${dy}px)`,
              clipPath: `inset(${insetTop}px ${insetSide}px 0px ${insetSide}px round ${startRadius}px)`,
            },
            {
              transform: "translate(0px, 0px)",
              clipPath: `inset(0px 0px 0px 0px round ${endRadius}px)`,
            },
          ],
          { duration: 620, easing: "cubic-bezier(0.22, 1, 0.36, 1)" }
        );
      }

      // Content rises and fades in just after the shape starts to open.
      const content = Array.from(container.children).find((c) => c.tagName !== "STYLE") as HTMLElement | undefined;
      content?.animate(
        [
          { opacity: 0, transform: "translateY(14px)" },
          { opacity: 1, transform: "translateY(0px)" },
        ],
        { duration: 420, delay: 140, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "backwards" }
      );
    } catch {
      // Cosmetic only.
    }
  }

  /** Placeholders the chatbox cycles through while idle: host `chatbox-placeholders` / init({ chatboxPlaceholders }) first, else this page's nudges, else the agent's suggestion labels, else generic defaults. */
  private getChatboxPlaceholders(): string[] {
    return this.collectChatboxPlaceholders().map(withTrailingEllipsis);
  }

  private collectChatboxPlaceholders(): string[] {
    const initConfig = (typeof window !== "undefined"
      ? (window as EkaMedAssistWindow).__ekaMedAssistConfig__
      : undefined) || {};
    let list: unknown = (initConfig as { chatboxPlaceholders?: unknown }).chatboxPlaceholders;
    if (!Array.isArray(list)) {
      try {
        list = JSON.parse(this.getAttribute("chatbox-placeholders") || "null");
      } catch {
        list = null;
      }
    }
    const clean = Array.isArray(list) ? list.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
    if (clean.length) return clean;

    // Agent data, read from the localStorage caches on every call so it
    // starts applying as soon as the nudge / config fetches have landed.
    const agentId = (initConfig as { agentId?: string }).agentId || this.getAttribute("agent-id") || "";
    const usable = (arr: unknown): string[] =>
      Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
    if (agentId) {
      // 1. Nudges for this page (most specific path first, then broader ones).
      try {
        const url = new URL(window.location.href);
        const hit = findFreshCachedNudge(agentId, url, getNudgePathCandidates(url.pathname));
        const nudges = usable(hit?.data.nudges);
        if (nudges.length) return nudges;
      } catch {
        // fall through
      }
      // 2. The agent's suggestion pills.
      const suggestions = usable(
        readAgentConfigCache(agentId)?.initial_message?.suggestions?.map((x) => x.label || x.value)
      );
      if (suggestions.length) return suggestions;
    }

    // 3. Generic defaults.
    return ["Ask me anything…", "Not sure what to ask? Just say hi…", "You can type in any language…"];
  }

  /** Grow the chatbox textarea with its content (up to its max-height, then scroll). */
  private autosizeChatbox(): void {
    const ta = this.shadowRoot?.getElementById("medassist-chatbox-input") as HTMLTextAreaElement | null;
    if (!ta) return;
    ta.style.height = "auto";
    const max = parseFloat(getComputedStyle(ta).maxHeight) || 92;
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`;
    ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
    this.updateChatboxFades();
  }

  /** Fade the top / bottom edge of the textarea only where there is more text beyond it. */
  private updateChatboxFades(): void {
    const ta = this.shadowRoot?.getElementById("medassist-chatbox-input") as HTMLTextAreaElement | null;
    if (!ta) return;
    ta.classList.toggle("fade-t", ta.scrollTop > 1);
    ta.classList.toggle("fade-b", ta.scrollHeight - ta.clientHeight - ta.scrollTop > 1);
  }

  /** The invitation pulse runs while the bar is idle, no chat is in progress, and nothing has been typed. */
  private syncChatboxPulse(): void {
    const shadowRoot = this.shadowRoot;
    const chatbox = shadowRoot?.getElementById("medassist-chatbox");
    const input = shadowRoot?.getElementById("medassist-chatbox-input") as HTMLTextAreaElement | null;
    if (!chatbox) return;
    const on = this.launcherState === "idle" && !this.chatStarted && !input?.value && !prefersReducedMotion();
    chatbox.classList.toggle("pulse", on);
  }

  /** Paint the right placeholder: "Continue your chat…" while a chat is in progress, hidden once the user types. */
  private syncChatboxPlaceholder(): void {
    const shadowRoot = this.shadowRoot;
    const ph = shadowRoot?.getElementById("medassist-chatbox-ph");
    if (!shadowRoot || !ph) return;
    const input = shadowRoot.getElementById("medassist-chatbox-input") as HTMLInputElement | null;
    const continuing = this.chatStarted && this.launcherState === "idle";
    ph.classList.toggle("gone", !!input?.value);
    const text = continuing ? "Continue your chat…" : this.getChatboxPlaceholders()[this.placeholderIndex % this.getChatboxPlaceholders().length];
    if (ph.textContent !== text) ph.textContent = text;
  }

  /** Every 3.5s the idle placeholder slides out and the next one slides in. Paused while typing, focused, loading, or with reduced motion. */
  private startPlaceholderRotation(): void {
    if (this.placeholderTimer) return;
    this.syncChatboxPlaceholder();
    if (prefersReducedMotion()) return;
    this.placeholderTimer = setInterval(() => {
      const shadowRoot = this.shadowRoot;
      const ph = shadowRoot?.getElementById("medassist-chatbox-ph");
      const input = shadowRoot?.getElementById("medassist-chatbox-input") as HTMLInputElement | null;
      if (!shadowRoot || !ph || !input) return;
      const list = this.getChatboxPlaceholders();
      if (list.length < 2 || document.hidden) return;
      if (this.chatStarted || this.launcherState !== "idle" || input.value || shadowRoot.activeElement === input) return;
      ph.classList.add("out");
      setTimeout(() => {
        this.placeholderIndex = (this.placeholderIndex + 1) % list.length;
        ph.classList.remove("out");
        ph.classList.add("in");
        this.syncChatboxPlaceholder();
        void ph.offsetWidth;
        ph.classList.remove("in");
      }, 220);
    }, 3500);
  }

  async loadWidgetCss(): Promise<void> {
    const shadowRoot = this.shadowRoot;
    if (!shadowRoot) {
      throw new Error("Shadow root is not available");
    }

    if (shadowRoot.querySelector("[data-medassist-style='true']")) {
      return;
    }

    const cssText = await getWidgetCssTextPromise();
    const styleTag = document.createElement("style");
    styleTag.setAttribute("data-medassist-style", "true");
    styleTag.textContent = cssText;
    shadowRoot.appendChild(styleTag);
  }

  loadWidgetModule(): Promise<WidgetModule> {
    if (!widgetModulePromise) {
      // Dynamic import resolves chunk URLs relative to the module's own URL.
      // When served from jsDelivr all chunks live in the same dist/ folder,
      // so the browser fetches them automatically without any manifest.
      widgetModulePromise = import(/* @vite-ignore */ WIDGET_JS_URL) as Promise<WidgetModule>;
    }
    return widgetModulePromise;
  }
}

customElements.define("eka-medassist-widget", MedAssistWidgetLoader);
