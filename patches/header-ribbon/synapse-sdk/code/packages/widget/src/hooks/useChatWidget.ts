import { useCallback, useEffect, useState, useRef, useMemo } from "react";
import { useChat } from "@/hooks/useChat";
import useMedAssistStore, { setStoreKey, hydrateStore } from "@/store/medAssistStore";
import {
  SYNAPSE_COMPONENTS,
  VOICE_AGENT_STATE,
  type ConnectionType,
  type Environment,
  type TContext,
  type TPastSession,
  type SYNAPSE_CONVERSATION,
  type TInitialMessage,
} from "@synapse/core";
import { type AgentFeedbackConfig } from "@/types/message";
import { AudioRecordingStatus, type TMessageOptions, CONNECTION_STATUS, } from "@/types/message";
import { SIDE_PANEL_DEFAULT_WIDTH, SIDE_PANEL_MIN_WIDTH, SIDE_PANEL_MAX_WIDTH } from "@/config";
import { validateFileBatch } from "@/lib/fileValidation";
import { useVoiceAgent } from "@/hooks/useVoiceAgent";
import { useStableCallback } from "@/hooks/useStableCallback";
import {
  emitMedAssistEvent,
  FEEDBACK_STATUS,
  FEEDBACK_TRIGGER,
  MEDASSIST_HOST_EVENTS,
  type FeedbackTrigger,
  type MedAssistHostEvent,
} from "@/lib/analytics";
import type { ChatComposerBundle } from "@/molecules/chat/ChatComposer";
import { useIsMobile } from "@/hooks/useResolvedMode";
import { channelFromDisplayMode } from "@/lib/channel";
import { resolveWidgetSize } from "@/lib/widgetSize";
import { useScrollManagement } from "@/hooks/useScrollManagement";
import type { TRibbonConfig } from "@/types/ribbon";
import { loadElicitationInput, loadFeedbackModal, loadWaitingTip, prefetchOnIdle } from "@/lib/prefetch";
import { COMPOSER_PLACEHOLDER_INTERVAL_MS, pickComposerPlaceholder } from "@/lib/composerPlaceholders";

export interface UseChatWidgetConfig {
  title: string;
  onClose: () => void;
  showCloseButton?: boolean;
  iconUrl?: string;
  environment: Environment;
  connectionType?: ConnectionType;
  baseUrl?: string;
  context?: TContext;
  displayMode?: "full" | "widget" | "side_panel";
  resize?: boolean;
  /** Only relevant when displayMode is "side_panel". Whether the host page's own content is shifted aside ("push", default) or the panel floats on top of it ("overlay"). */
  sidePanelMode?: "push" | "overlay";
  /** Only relevant when displayMode is "side_panel". Fixed panel width in px (default 400, clamped 320-560). */
  sidePanelWidth?: number;
  /** Only relevant when displayMode is "side_panel". Which viewport edge the panel docks to. Defaults to "right", or "left" when the document is RTL. */
  side?: "left" | "right";
  /** Only relevant when displayMode is "side_panel" with sidePanelMode "push". Fired on open/close so a host embed can shift its own page layout to make room. */
  onSidePanelPushChange?: (isPushed: boolean, widthPx: number, side: "left" | "right") => void;
  /** Partner JWT/JWE — the only host-supplied credential; absent -> guest. */
  authToken?: string;
  /**
   * Start a new chat: don't resume the stored session id, create a fresh one.
   * The identity (token pair, level, user_id) is preserved, so the user can
   * still browse their past sessions. Applied once, on the per-agent bootstrap.
   */
  force?: boolean;
  allowed?: SYNAPSE_CONVERSATION[];
  initialMessage?: TInitialMessage;
  /** Exit feedback config from agent-config API. When present, close intercepts to show the form. */
  feedback?: AgentFeedbackConfig;
  /** Text typed into the embed's chatbox launcher. Sent once per mount, as soon as the chat can take it. */
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
    hideWatermark?: boolean;
    explicitDisclaimer?: boolean;
    /** Agent-config `theme.consent_content`. Host-supplied consent/disclaimer copy; falls back to the built-in paragraphs when absent. */
    consentContent?: string | string[];
    /**
     * Agent-config `theme.upfront_consent`. When true, the chat is blocked
     * behind a consent form until the user accepts once (stored locally per
     * agent, like the feedback "don't show again" flag).
     */
    upfrontConsent?: boolean;
    /** Agent-config `theme.tips`. Shown while the bot works on a reply, until the end of the stream; absent or empty -> built-in tips. */
    tips?: string[];
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
    /** Where the floating (desktop "widget" mode) window opens: bottom-right "corner" (default) or "bottom-center". */
    openFrom?: "corner" | "bottom-center";
  };
}

export interface UseChatWidgetParams {
  isOpen: boolean;
  agentId: string;
  config: UseChatWidgetConfig;
}

const AGENT_CONFIG_CACHE_KEY = "eka-medassist-agent-config";

/** Client-only "ask this once" flags, stored per agent alongside the config cache. */
const FEEDBACK_HIDDEN_FLAG = "feedback_hidden";
const UPFRONT_CONSENT_FLAG = "upfront_consent_accepted";
// Longest the feedback form waits on the submit API before exiting anyway.
const FEEDBACK_SUBMIT_TIMEOUT_MS = 5000;
// Quiet time (bot done, composer empty) before the composer's circling
// attention ring switches on. Long enough that it never fires while the user
// is still reading the reply that just landed.
const COMPOSER_ATTENTION_DELAY_MS = 4000;

function readAgentFlag(agentId: string, flag: string): boolean {
  try {
    const raw = localStorage.getItem(AGENT_CONFIG_CACHE_KEY);
    const store: Record<string, Record<string, unknown>> = raw ? JSON.parse(raw) : {};
    return store[agentId]?.[flag] === true;
  } catch {
    return false;
  }
}

function writeAgentFlag(agentId: string, flag: string): void {
  try {
    const raw = localStorage.getItem(AGENT_CONFIG_CACHE_KEY);
    const store: Record<string, Record<string, unknown>> = raw ? JSON.parse(raw) : {};
    if (!store[agentId]) store[agentId] = {};
    store[agentId][flag] = true;
    localStorage.setItem(AGENT_CONFIG_CACHE_KEY, JSON.stringify(store));
  } catch {
    // non-critical; ignore storage errors
  }
}

export function useChatWidget({ isOpen, agentId: agentIdProp, config }: UseChatWidgetParams) {
  // Voice agent
  const {
    state: voiceAgentState,
    isMuted,
    connect: connectVoiceAgent,
    disconnect: disconnectVoiceAgent,
    reset: resetVoiceAgent,
    toggleMute,
  } = useVoiceAgent();

  const handleVoiceAgentClick = useStableCallback(() => {
    if (voiceAgentState === VOICE_AGENT_STATE.IDLE) {
      connectVoiceAgent();
    }
  });

  const isVoiceAgentActive = voiceAgentState !== VOICE_AGENT_STATE.IDLE;

  // Local state
  const [inputValue, setInputValue] = useState("");
  const [isRecording, setIsRecording] = useState(false);

  // Display mode is split in two:
  //   - store `displayMode` stays pinned to `config.displayMode` (the host's
  //     original intent). `ProfileHeader` reads this to decide whether the
  //     close button is shown — full-mode hosts must keep it hidden so the
  //     user can't close into a blank screen.
  //   - `localDisplayMode` is the visual toggle. It seeds from config and
  //     mutates only in-memory, never touching the store.
  const [localDisplayMode, setLocalDisplayMode] = useState<"full" | "widget" | "side_panel">(
    config.displayMode === "full" ? "full" : config.displayMode === "side_panel" ? "side_panel" : "widget"
  );
  const toggleDisplayMode = useCallback(
    () => setLocalDisplayMode((m) => (m === "full" ? "widget" : "full")),
    []
  );
  const isMobile = useIsMobile();
  const resolvedMode: "mobile" | "widget" | "full" | "side_panel" = isMobile ? "mobile" : localDisplayMode;

  // Side-panel config is static (host-set at init, no runtime toggle) — resolved
  // once here and threaded through as plain values, never persisted to the store.
  const resolvedSide: "left" | "right" =
    config.side ?? (typeof document !== "undefined" && document.dir === "rtl" ? "left" : "right");
  const resolvedSidePanelWidth = Math.min(
    Math.max(config.sidePanelWidth ?? SIDE_PANEL_DEFAULT_WIDTH, SIDE_PANEL_MIN_WIDTH),
    SIDE_PANEL_MAX_WIDTH
  );
  const resolvedSidePanelMode: "push" | "overlay" = config.sidePanelMode ?? "push";

  // Floating-window size: host override -> agent config -> 384x600, clamped.
  // Static like the side-panel config. Read from config.theme (not mergedTheme in
  // WidgetContainer, whose mergeTheme keeps only the colour keys).
  const resolvedWidgetSize = useMemo(() => resolveWidgetSize(config.theme), [config.theme]);
  const [attachmentFiles, setAttachmentFiles] = useState<File[]>([]);
  const hasInitializedRef = useRef(false);
  const [hasAttachment, setHasAttachment] = useState(false);
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);
  // Seeded from storage rather than an effect: starting `true` and correcting
  // afterwards would flash the consent form at users who already accepted.
  const [showConsentModal, setShowConsentModal] = useState(
    () => !!config.theme?.upfrontConsent && !readAgentFlag(agentIdProp, UPFRONT_CONSENT_FLAG)
  );
  // Tracks the agentId we already bootstrapped session storage / SDK init for.
  // Without this, the session-init effect re-runs whenever `agentId` flips
  // between its store-default and the prop-supplied value, even though the
  // bootstrap is single-shot per (tab, agent).
  const initializedAgentIdRef = useRef<string | null>(null);

  // Store — one selector per field, never a bare `useMedAssistStore()`.
  // A whole-store subscription re-renders this hook (and with it the entire
  // widget tree) on EVERY store write, including per-token streaming updates.
  // Setters are referentially stable, so selecting them never re-renders.
  const startNewConnection = useMedAssistStore((s) => s.startNewConnection);
  const showRetryButton = useMedAssistStore((s) => s.showRetryButton);
  const clearError = useMedAssistStore((s) => s.clearError);
  const error = useMedAssistStore((s) => s.error);
  const connectionStatus = useMedAssistStore((s) => s.connectionStatus);
  const recordingStatus = useMedAssistStore((s) => s.recordingStatus);
  const isWaitingForResponse = useMedAssistStore((s) => s.isWaitingForResponse);
  const isStreaming = useMedAssistStore((s) => s.isStreaming);
  const setError = useMedAssistStore((s) => s.setError);
  const sessionId = useMedAssistStore((s) => s.sessionId);
  const initialMessage = useMedAssistStore((s) => s.initialMessage);
  const sessionInitialMessages = useMedAssistStore((s) => s.sessionInitialMessages);

  const elicitationState = useMedAssistStore((s) => s.elicitationState);
  const userLevel = useMedAssistStore((s) => s.level);

  // Chat hook
  const {
    incomingMessages,
    isLoadingSessionMessages,
    sendMessage,
    handleInitialTaskClick,
    markWidgetOpened,
    startSession,
    startNewChat,
    isReady,
    startRecording,
    stopRecording,
    handleRetry,
    isValidFile,
    sendMessageFeedback,
    clearElicitationState,
    sendSessionFeedback,
    getPastSessions,
  } = useChat({
    environment: config.environment,
    connectionType: config.connectionType,
    onInlineText: (text) => {
      setInputValue((prev) => prev + text);
    },
    baseUrl: config.baseUrl ? config.baseUrl : undefined,
    context: config?.context,
    ...(config?.authToken && { authToken: config.authToken }),
    ...(config?.force && { force: config.force }),
    // How the widget opened decides the API channel: widget / web / side_panel.
    channel: channelFromDisplayMode(config.displayMode),
  });

  // `useChat` re-creates its returned functions on every render. The ones that
  // flow down as props are wrapped here so the memoized components below them
  // (ChatMessage, ChatComposer, SessionList) actually bail on unchanged props.
  const handleRetryStable = useStableCallback(handleRetry);
  const sendMessageFeedbackStable = useStableCallback(sendMessageFeedback);
  const clearElicitationStateStable = useStableCallback(clearElicitationState);

  // Session list actions — shared by the fullscreen sidebar and the drawer.
  const handleSelectSession = useStableCallback((id: string) => {
    void startSession({ sessionId: id });
  });
  const handleStartNewChat = useStableCallback(() => {
    void startNewChat();
  });

  // Session drawer state
  const [isSessionDrawerOpen, setIsSessionDrawerOpen] = useState(false);
  const [pastSessions, setPastSessions] = useState<TPastSession[]>([]);
  // Seeded `true`, not `false`: the fullscreen rail's fetch is kicked off by an
  // effect, which runs *after* the first paint. Starting false would flash the
  // "No past chats" empty state for a frame before the shimmer appears.
  const [isLoadingPastSessions, setIsLoadingPastSessions] = useState(true);

  // `useChat` re-creates `getPastSessions` on every render, so hold it behind a
  // ref. Depending on it directly would make `refreshPastSessions` unstable and
  // send the fullscreen-sidebar effect below into a fetch-per-render loop.
  const getPastSessionsRef = useRef(getPastSessions);
  useEffect(() => {
    getPastSessionsRef.current = getPastSessions;
  });

  const refreshPastSessions = useCallback(async () => {
    setIsLoadingPastSessions(true);
    try {
      const sessions = await getPastSessionsRef.current();
      setPastSessions(sessions);
    } catch {
      // non-critical — callers keep whatever list they already have
    } finally {
      setIsLoadingPastSessions(false);
    }
  }, []);

  const openSessionDrawer = useCallback(async () => {
    setIsSessionDrawerOpen(true);
    await refreshPastSessions();
  }, [refreshPastSessions]);

  const closeSessionDrawer = useCallback(() => {
    setIsSessionDrawerOpen(false);
  }, []);

  // Fullscreen sidebar: sessions live in a persistent left rail rather than an
  // on-demand drawer, so the list has to be fetched without a user gesture.
  // Re-runs on sessionId change so a newly started chat shows up (and the
  // "CURRENT CHAT" badge lands on the right row).
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const toggleSidebar = useCallback(() => setIsSidebarCollapsed((v) => !v), []);

  useEffect(() => {
    if (resolvedMode !== "full" || userLevel !== "user") return;
    void refreshPastSessions();
  }, [resolvedMode, userLevel, sessionId, refreshPastSessions]);

  // Session init.
  //
  // Two responsibilities, decoupled so they don't fight each other:
  //  1. Per-agent bootstrap (storage key, hydrate, displayMode seed, context):
  //     run *once* per agentIdProp via initializedAgentIdRef. The store's
  //     `agentId` field flips between its default and the prop value during
  //     hydration; depending on it would re-run the bootstrap on every flip.
  //  2. startSession gate: fires when isOpen + isReady go true the first time.
  //
  // SINGLE-SHOT CONTRACT: the dep list is deliberately [isOpen, isReady,
  // agentIdProp] — narrower than everything the body reads. The refs above
  // guarantee each block runs at most once per (tab, agent), so `config.*`
  // values are snapshot at bootstrap by design (they're static host config),
  // and store actions are read via getState() so nothing here depends on a
  // render-time closure. If you relax the ref guards, revisit the dep list.
  useEffect(() => {
    if (!agentIdProp) {
      console.error("Agent ID is required");
      return;
    }
    if (initializedAgentIdRef.current !== agentIdProp) {
      const store = useMedAssistStore.getState();
      setStoreKey(agentIdProp);

      hydrateStore(agentIdProp);
      store.setAgentId(agentIdProp);

      // `force` means "start a new chat", not "start a new login". Hydrate
      // first so the persisted identity is in memory, then drop only the
      // session-scoped state — clearSession keeps the token pair, level and
      // user_id, which is what lets the user still browse their past sessions.
      // (Wiping the whole persisted entry here would re-exchange them as a
      // guest and hide their own history.)
      if (config.force) {
        store.clearSession();
      }

      // displayMode is not persisted — always seed from config on bootstrap.
      // Toggle button still mutates in-memory state for the lifetime of the mount.
      if (config.displayMode === "full" || config.displayMode === "widget" || config.displayMode === "side_panel") {
        store.setDisplayMode(config.displayMode);
        store.setInitialDisplayMode(config.displayMode);
      }

      if (config?.context && Object.keys(config?.context || {}).length) {
        store.setContext(config.context);
      }

      // initialMessage now comes from the agent-config API (resolved by widget-embed
      // before mount). Seed it here on bootstrap so useChat's consumer effect can
      // render the greeting + suggestion pills on first paint. Not persisted —
      // every mount re-seeds from config to keep behaviour consistent with how
      // theme/allowed/connectivity are sourced.
      if (config?.initialMessage?.text || config?.initialMessage?.suggestions?.length) {
        store.setInitialMessage(config.initialMessage);
      }

      initializedAgentIdRef.current = agentIdProp;
    }

    if (isOpen && isReady && !hasInitializedRef.current) {
      hasInitializedRef.current = true;
      startSession({ forceNewSession: false });
    }
  }, [isOpen, isReady, agentIdProp]);

  // Every open of the widget is a new visit for the host's milestone events
  // (`connection_established`, `first_message_sent`, `first_bot_reply`): each fires again after
  // a reopen, the way a page view repeats. The embed unmounts the widget on
  // close, so this is for hosts that keep it mounted and only hide it.
  useEffect(() => {
    if (isOpen) markWidgetOpened();
  }, [isOpen]);

  // Warm the auth-input chunk (mobile/OTP/email) once first paint is done. It
  // is split out of the entry, but an auth elicitation can be the very first
  // tool call, so fetch it on idle rather than on demand.
  // The waiting tip is split out the same way and is needed on the first send.
  useEffect(() => {
    prefetchOnIdle([loadElicitationInput, loadWaitingTip]);
  }, []);

  // The exit feedback form, only for agents that have one. Keyed on the config
  // because it can land after mount (background agent-config refresh).
  useEffect(() => {
    if (config.feedback) prefetchOnIdle([loadFeedbackModal]);
  }, [config.feedback]);

  // Voice agent cleanup
  useEffect(() => {
    return () => {
      disconnectVoiceAgent();
    };
  }, []);

  // Upfront consent. The agent-config theme can land after mount (the host
  // refreshes its cached config in the background), so a flag that flips on
  // late still raises the form. It never re-raises after acceptance — the
  // stored flag gates it.
  useEffect(() => {
    if (!config.theme?.upfrontConsent || !agentIdProp) return;
    if (readAgentFlag(agentIdProp, UPFRONT_CONSENT_FLAG)) return;
    setShowConsentModal(true);
  }, [config.theme?.upfrontConsent, agentIdProp]);

  const handleConsentAccept = useCallback(() => {
    writeAgentFlag(agentIdProp, UPFRONT_CONSENT_FLAG);
    setShowConsentModal(false);
  }, [agentIdProp]);

  // Feedback modal handlers — intercept close when feedback config is present
  const shouldAskFeedback = useCallback(
    () => !!config.feedback && !readAgentFlag(agentIdProp, FEEDBACK_HIDDEN_FLAG),
    [config.feedback, agentIdProp]
  );

  // Back-press guard. A browser/hardware back press never reaches onClose, so
  // to ask for feedback on it we park one extra history entry on top of the
  // page while the widget is open, and treat its pop as "the user wants out".
  // In widget/side_panel mode that closes the widget and leaves the host page
  // where it was. The entry copies the host's history.state, so a host router
  // popping back to its own entry finds the state it wrote.
  // Pushed only after the first user activation — Chrome skips history
  // entries added without one, which would make back leave the page outright.
  const backGuardEnabled = isOpen && !!config.feedback;
  const backGuardArmedRef = useRef(false);
  const isExitingRef = useRef(false);

  const armBackGuard = useCallback(() => {
    if (backGuardArmedRef.current || isExitingRef.current) return;
    backGuardArmedRef.current = true;
    window.history.pushState({ ...window.history.state, medassistBackGuard: true }, "");
  }, []);

  // The one way out. If our history entry is still parked, pop it first so the
  // host's onClose starts from the real page entry — otherwise a host that
  // navigates via history.back() would only pop our entry and stay put, and one
  // that sets location.href would leave a duplicate entry for the user to back
  // through.
  const exitWidget = useStableCallback(() => {
    if (isExitingRef.current) return;
    isExitingRef.current = true;
    setShowFeedbackModal(false);
    if (!backGuardArmedRef.current) {
      config.onClose();
      return;
    }
    backGuardArmedRef.current = false;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.removeEventListener("popstate", finish);
      config.onClose();
    };
    window.addEventListener("popstate", finish);
    // popstate can be swallowed (e.g. bfcache quirks); never strand the user.
    setTimeout(finish, 500);
    window.history.back();
  });

  // What opened the form, kept for the feedback events that follow it.
  const feedbackTriggerRef = useRef<FeedbackTrigger>(FEEDBACK_TRIGGER.CLOSE_BUTTON);
  const isFeedbackOpenRef = useRef(false);

  // Feedback events read the session id via getState(): they fire from async
  // and event-listener paths where the selected value can be stale.
  const emitFeedbackEvent = useStableCallback((name: MedAssistHostEvent, detail: Record<string, unknown> = {}) => {
    const currentSessionId = useMedAssistStore.getState().sessionId;
    emitMedAssistEvent(name, {
      ...(currentSessionId && { sessionId: currentSessionId }),
      trigger: feedbackTriggerRef.current,
      formType: config.feedback?.type ?? "default",
      ...detail,
    });
  });

  const openFeedbackForm = useStableCallback((trigger: FeedbackTrigger) => {
    feedbackTriggerRef.current = trigger;
    isFeedbackOpenRef.current = true;
    setShowFeedbackModal(true);
  });

  const handleClose = useStableCallback(() => {
    if (shouldAskFeedback()) {
      openFeedbackForm(FEEDBACK_TRIGGER.CLOSE_BUTTON);
    } else {
      exitWidget();
    }
  });

  useEffect(() => {
    if (!backGuardEnabled || !shouldAskFeedback()) return;
    const onFirstInteraction = () => armBackGuard();
    const onPopState = () => {
      // Only our own entry being popped counts; exitWidget handles its own pop.
      if (!backGuardArmedRef.current || isExitingRef.current) return;
      backGuardArmedRef.current = false;
      // Back while the form is already up is a second "get me out": leave.
      if (shouldAskFeedback() && !isFeedbackOpenRef.current) {
        openFeedbackForm(FEEDBACK_TRIGGER.BACK);
      } else {
        exitWidget();
      }
    };
    // click, not pointerdown: on touch screens Chrome only grants user
    // activation at touchend, and a push before that is skipped on back.
    window.addEventListener("click", onFirstInteraction, { capture: true, once: true });
    window.addEventListener("keydown", onFirstInteraction, { capture: true, once: true });
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("click", onFirstInteraction, { capture: true });
      window.removeEventListener("keydown", onFirstInteraction, { capture: true });
      window.removeEventListener("popstate", onPopState);
    };
  }, [backGuardEnabled, shouldAskFeedback, armBackGuard, exitWidget, openFeedbackForm]);

  // Waits for the feedback API before leaving: the host's onClose usually
  // navigates the page, and a navigation cancels any request still in flight.
  // Capped so a hung request can't trap the user on the form.
  const handleSessionFeedbackSubmit = useStableCallback(
    async (selectedValues: string[], npsScore?: number, dontShowAgain?: boolean) => {
      if (dontShowAgain) writeAgentFlag(agentIdProp, FEEDBACK_HIDDEN_FLAG);
      const hasFeedback = selectedValues.length > 0 || !!npsScore;
      let status: string = FEEDBACK_STATUS.NOT_SENT;
      if (hasFeedback) {
        const sent = await Promise.race([
          sendSessionFeedback(selectedValues, npsScore),
          new Promise<null>((resolve) => setTimeout(() => resolve(null), FEEDBACK_SUBMIT_TIMEOUT_MS)),
        ]);
        status = sent === null ? FEEDBACK_STATUS.TIMEOUT : sent ? FEEDBACK_STATUS.SUCCESS : FEEDBACK_STATUS.FAILED;
      }
      emitFeedbackEvent(MEDASSIST_HOST_EVENTS.FEEDBACK_SUBMITTED, {
        ...(npsScore && { npsScore }),
        options: selectedValues.join(","),
        optionCount: selectedValues.length,
        dontShowAgain: !!dontShowAgain,
        status,
      });
      exitWidget();
    }
  );

  const handleSessionFeedbackSkip = useStableCallback(() => {
    emitFeedbackEvent(MEDASSIST_HOST_EVENTS.FEEDBACK_SKIPPED);
    exitWidget();
  });

  // Backdrop dismiss: the user chose to stay. If they got here via back, the
  // guard entry is gone, so park a new one — this click is a user interaction.
  const handleCloseModal = useStableCallback(() => {
    isFeedbackOpenRef.current = false;
    setShowFeedbackModal(false);
    emitFeedbackEvent(MEDASSIST_HOST_EVENTS.FEEDBACK_DISMISSED);
    if (backGuardEnabled) armBackGuard();
  });

  // Derived values
  const inConversation = incomingMessages.length > 0;
  const isFirstMessage = incomingMessages.length === 1;

  //active elicitation is used for displaying the chat composer elicitation components
  const activeElicitation = useMemo(() => {
    const lastMessage = incomingMessages[incomingMessages.length - 1];
    const lastToolKey = lastMessage?.tool_keys?.[lastMessage.tool_keys.length - 1];
    if (!lastToolKey) return null;
    const entry = elicitationState[lastToolKey];
    if (!entry?.active) return null;
    return { ...entry, tool_key: lastToolKey };
  }, [incomingMessages, elicitationState]);


  // Resolve the initial message with per-session precedence:
  //  1. the initial_message the create-session API returned for THIS sessionId
  //     (persisted per session, so a refresh resuming the same session reuses it),
  //  2. else the flat store value (config seed / most recent create-session POST),
  //  3. else the outer config API value.
  const resolvedInitialMessage = useMemo(() => {
    return (
      (sessionId ? sessionInitialMessages[sessionId] : undefined) ??
      initialMessage ??
      config?.initialMessage ??
      null
    );
  }, [sessionId, sessionInitialMessages, initialMessage, config?.initialMessage]);

  const hasInitialMessage = useMemo(() => {
    return !!resolvedInitialMessage?.text || !!resolvedInitialMessage?.suggestions?.length;
  }, [resolvedInitialMessage]);

  // While a past session's transcript is loading, `incomingMessages` is briefly
  // empty — without this guard fullscreen would swap in the greeting/empty
  // state for that window instead of letting the chat column shimmer.
  const isEmptyChat = useMemo(() => {
    return hasInitialMessage &&
      incomingMessages?.length === 0 &&
      !isLoadingSessionMessages;
  }, [incomingMessages, hasInitialMessage, isLoadingSessionMessages])

  const isAuthComponent = useMemo(() => {
    if (!activeElicitation) return false;
    return activeElicitation.component === SYNAPSE_COMPONENTS.MOBILE ||
      activeElicitation.component === SYNAPSE_COMPONENTS.OTP ||
      activeElicitation.component === SYNAPSE_COMPONENTS.EMAIL;
  }, [activeElicitation]);

  // All scroll concerns live here — RAF coalescing, mode-toggle re-anchor,
  // ResizeObserver-driven follow on content growth, and reduced-motion support.
  const {
    scrollAreaRef,
    messagesEndRef,
    showScrollButton,
    isRestoring,
    scrollToBottom,
  } = useScrollManagement({
    messageCount: incomingMessages.length,
    isStreaming,
    isFirstMessage,
    resolvedMode,
  });

  const isConnected = connectionStatus === CONNECTION_STATUS.CONNECTED;
  const isComposerDisabled = isWaitingForResponse || isStreaming;

  // Attention ring on the composer. The bot has finished (composer enabled,
  // connected, no error), nothing is being recorded or attached, and the user
  // hasn't typed anything — so the circling border nudges them to reply. It
  // arms after COMPOSER_ATTENTION_DELAY_MS of that quiet so it never flashes
  // right as a reply lands, and drops the instant any of those change.
  const isComposerIdle =
    !isComposerDisabled &&
    isConnected &&
    !error &&
    !isVoiceAgentActive &&
    !isRecording &&
    recordingStatus === AudioRecordingStatus.IDLE &&
    !hasAttachment &&
    inputValue.trim().length === 0;
  const [showComposerAttention, setShowComposerAttention] = useState(false);
  useEffect(() => {
    if (!isComposerIdle) {
      setShowComposerAttention(false);
      return;
    }
    const timer = setTimeout(() => setShowComposerAttention(true), COMPOSER_ATTENTION_DELAY_MS);
    return () => clearTimeout(timer);
  }, [isComposerIdle]);

  const recordingStatusPlaceholder = useMemo(() => {
    return recordingStatus === AudioRecordingStatus.IDLE
      ? null
      : recordingStatus === AudioRecordingStatus.LISTENING
        ? "Listening..."
        : recordingStatus === AudioRecordingStatus.PROCESSING
          ? "Processing..."
          : recordingStatus === AudioRecordingStatus.TRANSCRIBING
            ? "Transcribing..."
            : null;
  }, [recordingStatus]);

  // Rotating placeholder. While the composer sits idle (same condition as the
  // attention ring) the empty box cycles through generic hints every few
  // seconds. Rotation pauses the moment the user types or the bot replies,
  // and resets to the resting sentence so it never resumes mid-list.
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  useEffect(() => {
    if (!isComposerIdle) {
      setPlaceholderIndex(0);
      return;
    }
    const timer = setInterval(
      () => setPlaceholderIndex((i) => i + 1),
      COMPOSER_PLACEHOLDER_INTERVAL_MS
    );
    return () => clearInterval(timer);
  }, [isComposerIdle]);

  // Agent-config tips shown until END_OF_STREAM. Passed raw: the built-in
  // fallback list lives in the lazily loaded tip chunk, not the entry.
  const waitingTips = config.theme?.tips;

  const composerPlaceholder = recordingStatusPlaceholder && recordingStatus !== AudioRecordingStatus.IDLE
    ? recordingStatusPlaceholder
    : isWaitingForResponse || isStreaming
      ? "Please wait for the response..."
      : pickComposerPlaceholder(placeholderIndex);

  // Handlers
  const handleSendMessage = useStableCallback(async (options?: TMessageOptions, firstMessage?: Boolean) => {
    if (isComposerDisabled) {
      return;
    }
    const resolvedSendMessageFn = firstMessage ? handleInitialTaskClick : sendMessage
    const messageToSend = options?.message ?? inputValue;

    if (attachmentFiles.length > 0) {
      await resolvedSendMessageFn({
        files: attachmentFiles,
        message: messageToSend.trim(),
      });
      setAttachmentFiles([]);
      setHasAttachment(false);
    } else if (messageToSend.trim()) {
      await resolvedSendMessageFn({ ...options, message: messageToSend.trim() });
    } else if (options?.resend) {
      await resolvedSendMessageFn(options);
    } else if (!!options) {
      await resolvedSendMessageFn(options);
    }

    setInputValue("");
    setIsRecording(false);
    setHasAttachment(false);
    // Scrolling is handled by the messages effect in ChatWidget — it anchors
    // the new user message to the top of the viewport.
  });

  // Message-list sends route through handleInitialTaskClick while the chat is
  // still empty; the empty-state screen always does. Stable wrappers so the
  // memoized message list doesn't re-render when `isEmptyChat` flips.
  const handleChatSendMessage = useStableCallback((options: TMessageOptions) =>
    handleSendMessage(options, isEmptyChat)
  );
  const handleEmptyStateSendMessage = useStableCallback((options: TMessageOptions) =>
    handleSendMessage(options, true)
  );

  // Chatbox launcher hand-off: the embed mounts the widget only once the user
  // sends from its chatbox, passing that text here. It goes out exactly like a
  // composer send, but only once the chat can take it — session ready and
  // connected, consent accepted, a resumed transcript loaded and no reply in
  // flight. `isReady` matters: `connectionStatus` is persisted, so on a remount
  // it can still read CONNECTED from the previous mount.
  const firstUserMessageSentRef = useRef(false);
  useEffect(() => {
    const text = config.firstUserMessage?.trim();
    if (!text || firstUserMessageSentRef.current) return;
    if (!isReady || !isConnected || showConsentModal || isLoadingSessionMessages || isComposerDisabled) return;
    firstUserMessageSentRef.current = true;
    void handleSendMessage({ message: text });
  }, [config.firstUserMessage, isReady, isConnected, showConsentModal, isLoadingSessionMessages, isComposerDisabled, handleSendMessage]);

  const handleFileChange = useStableCallback((files: File[]) => {
    if (files && files.length > 0) {
      const validFiles = files.filter((file) => isValidFile(file));
      if (validFiles.length === 0) return;
      const batchError = validateFileBatch(validFiles, attachmentFiles.length);
      if (batchError) {
        setError(batchError);
        return;
      }
      files = validFiles;
    }
    setAttachmentFiles((prev) => {
      setHasAttachment((prev?.length ?? 0) + (files?.length ?? 0) > 0);
      return [...prev, ...files];
    });
  });

  const handleRemoveFile = useCallback((index: number) => {
    setAttachmentFiles((prev) => {
      const newFiles = prev.filter((_, i) => i !== index);
      setHasAttachment(newFiles.length > 0);
      return newFiles;
    });
  }, []);

  const handleRecording = useStableCallback(async () => {
    if (isRecording) {
      await stopRecording();
      setIsRecording(false);
    } else {
      if (isComposerDisabled) return;
      try {
        await startRecording();
        setIsRecording(true);
      } catch (error) {
        console.warn("useChatWidget: starting recording failed", error);
      }
    }
  });

  // Composer keystrokes.
  const handleInputChange = useStableCallback((value: string) => {
    setInputValue(value);
  });

  // Pre-built composer props. Memoized (with stable handlers above) so the
  // memoized ChatComposer doesn't re-render on every stream chunk.
  const chatComposerProps = useMemo<ChatComposerBundle>(() => ({
    value: inputValue,
    onChange: handleInputChange,
    onSend: handleSendMessage,
    onFileChange: handleFileChange,
    onRemoveFile: handleRemoveFile,
    onRecording: handleRecording,
    isRecording,
    hasAttachment,
    attachmentFiles,
    isDisabled: isComposerDisabled,
    placeholder: composerPlaceholder,
    recordingStatus,
    allowed: config.allowed,
    isVoiceAgentActive,
    handleVoiceMode: handleVoiceAgentClick,
    showAttention: showComposerAttention,
  }), [
    inputValue,
    handleInputChange,
    handleSendMessage,
    handleFileChange,
    handleRemoveFile,
    handleRecording,
    isRecording,
    hasAttachment,
    attachmentFiles,
    isComposerDisabled,
    composerPlaceholder,
    recordingStatus,
    config.allowed,
    isVoiceAgentActive,
    handleVoiceAgentClick,
    showComposerAttention,
  ]);

  // Modal prop bundles — built here (not inline in ChatWidget's JSX) so their
  // identity is stable between the renders that don't touch them.
  const feedbackModalProps = useMemo(() => (config.feedback ? {
    isOpen: showFeedbackModal,
    config: config.feedback,
    onSubmit: handleSessionFeedbackSubmit,
    onSkip: handleSessionFeedbackSkip,
    onClose: handleCloseModal,
  } : undefined), [
    config.feedback,
    showFeedbackModal,
    handleSessionFeedbackSubmit,
    handleSessionFeedbackSkip,
    handleCloseModal,
  ]);

  const consentModalProps = useMemo(() => (config.theme?.upfrontConsent ? {
    isOpen: showConsentModal,
    onAccept: handleConsentAccept,
  } : undefined), [config.theme?.upfrontConsent, showConsentModal, handleConsentAccept]);

  // ChatWidget is the hook's only consumer — every key below has a consumer
  // there. Values that only feed the composer/modals travel inside the
  // pre-built prop bundles instead of as loose duplicates.
  return {
    waitingTips,
    // State
    showScrollButton,
    isRestoring,

    // Display mode
    toggleDisplayMode,
    resolvedMode,                  // rendered mode: "mobile" | "widget" | "full" | "side_panel"

    // Side panel (only meaningful when resolvedMode === "side_panel")
    sidePanelMode: resolvedSidePanelMode,
    sidePanelWidth: resolvedSidePanelWidth,
    widgetWidth: resolvedWidgetSize.width,
    widgetHeight: resolvedWidgetSize.height,
    openFrom: (config.theme?.openFrom === "bottom-center" ? "bottom-center" : "corner") as "corner" | "bottom-center",
    side: resolvedSide,
    onSidePanelPushChange: config.onSidePanelPushChange,
    // Refs
    scrollAreaRef,
    messagesEndRef,

    // Store values
    startNewConnection,
    showRetryButton,
    clearError,
    error,
    sessionId,
    activeElicitation,

    // Derived
    inConversation,
    isFirstMessage,
    isEmptyChat,
    isAuthComponent,
    isConnected,
    isComposerDisabled,
    isLoadingSessionMessages,
    initialMessage: resolvedInitialMessage,

    // Chat hook values (stable wrappers — see useStableCallback above)
    incomingMessages,
    sendMessageFeedback: sendMessageFeedbackStable,
    clearElicitationState: clearElicitationStateStable,
    handleRetry: handleRetryStable,

    // Handlers
    handleChatSendMessage,
    handleEmptyStateSendMessage,
    handleSelectSession,
    handleStartNewChat,
    scrollToBottom,
    handleClose,

    // Composer props (pre-built)
    chatComposerProps,

    // Modal props (pre-built)
    feedbackModalProps,
    consentModalProps,

    // Session drawer / sidebar — both gated on theme.feature
    isSessionDrawerOpen,
    pastSessions,
    isLoadingPastSessions,
    openSessionDrawer,
    closeSessionDrawer,

    // Fullscreen session sidebar
    userLevel,
    isSidebarCollapsed,
    toggleSidebar,

    // Voice
    voiceAgentState,
    isMuted,
    isVoiceAgentActive,
    disconnectVoiceAgent,
    resetVoiceAgent,
    toggleMute,
  };
}
