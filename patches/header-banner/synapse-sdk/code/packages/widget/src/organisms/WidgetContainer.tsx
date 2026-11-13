import { useCallback, useEffect, useLayoutEffect, useState, useRef, useMemo, Suspense, lazy } from "react";
import { type VoiceAgentState } from "@/hooks/useVoiceAgent";
import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "../lib/utils";
import { type TElicitationEntry, type TMessageOptions } from "@/types/message";
import { useDraggable } from "@/hooks/useDraggable";
import { WIDGET_DIMENSIONS, WIDGET_VIEWPORT_PADDING } from "@/config";
import { applyTheme } from "../utils/theme";
import { mergeTheme } from "../config/theme";
import useMedAssistStore from "@/store/medAssistStore";
import { VOICE_AGENT_STATE } from "@synapse/core";
import { ComposerSkeleton } from "@/atoms/Skeleton";
import { Info } from "lucide-react";

// First-paint-critical: header + composer are always rendered on open, so
// import them statically (they fold into the main chunk) rather than paying a
// dynamic-import round-trip before the widget can show.
import ProfileHeader from "../molecules/header/ProfileHeader";
import HeaderBanner from "../molecules/banner/HeaderBanner";
import ChatComposer, { type ChatComposerBundle } from "../molecules/chat/ChatComposer";
import { useWidgetHeader } from "@/context/WidgetHeaderContext";
// Global toast overlay — mounted at the always-rendered content wrapper so it
// shows in every state (empty screen, chat, voice), not just the chat branch.
import DispToastHost from "../molecules/chat/DispToastHost";
import DisclaimerModal from "../molecules/DisclaimerModal";
import ConsentModal from "../molecules/consent/ConsentModal";
import { loadFeedbackModal } from "@/lib/prefetch";
import { type AgentFeedbackConfig } from "@/types/message";

// Split out of the entry: the form only shows on exit. If its chunk can't be
// fetched (offline at the moment of closing), skip straight to the exit rather
// than leave the user unable to close the widget.
const FeedbackModal = lazy(() =>
  loadFeedbackModal().catch((error) => {
    console.warn("[medassist] feedback-form chunk failed to load; closing without it", error);
    return { default: FeedbackModalUnavailable };
  })
);

function FeedbackModalUnavailable({ onSkip }: { onSkip: () => void }) {
  useEffect(() => {
    onSkip();
  }, [onSkip]);
  return null;
}

type Environment = "development" | "production" | "staging";

interface WidgetContainerProps {
  isOpen: boolean;
  children: ReactNode;
  /** Optional sidebar rendered to the left of the chat area (fullscreen mode) */
  sidebar?: ReactNode;
  /** Session drawer overlay */
  sessionDrawer?: ReactNode;
  /**
   * Fullscreen-desktop-only: when provided, replaces children (e.g. empty state).
   *
   * Render-prop form: the container builds `composer` and `composerFooter`
   * locally (so it owns Suspense + ChatComposer wiring) and hands them to
   * the host. The host decides where to slot them. Compared to a
   * `cloneElement(...)` patch this keeps the slot contract explicit and
   * type-checked, and lets the host change empty-state markup freely.
   */
  fullScreenEmptyState?: (slots: {
    composer: ReactNode;
    composerFooter: ReactNode;
  }) => ReactNode;
  sessionId?: string;
  environment: Environment;
  chatComposer?: ChatComposerBundle;
  /**
   * Resolved render mode — single source of truth for layout.
   *
   * Computed upstream by `useResolvedMode`, which folds together:
   *  - the user's "widget" | "full" preference (`useMedAssistStore.displayMode`)
   *  - device/viewport mobile detection (overrides preference to "mobile")
   *
   * The resulting "mobile" | "widget" | "full" | "side_panel" is the *only*
   * mode signal this component should react to — drives sidebar visibility,
   * edge-to-edge sizing, drag-enable, etc. via `isFullScreenDesktop = mode === "full"`
   * and `isSidePanel = mode === "side_panel"`.
   */
  mode: "mobile" | "widget" | "full" | "side_panel";
  /** Only relevant when mode is "side_panel". Whether the host page's own content is shifted aside ("push") or the panel floats on top of it ("overlay"). */
  sidePanelMode?: "push" | "overlay";
  /** Only relevant when mode is "side_panel". Fixed panel width in px. */
  sidePanelWidth?: number;
  /** Only relevant when mode is "widget" (desktop floating). Window width in px; defaults to 384. */
  widgetWidth?: number;
  /** Only relevant when mode is "widget" (desktop floating). Window height in px; defaults to 600. */
  widgetHeight?: number;
  /** Only relevant when mode is "widget" (desktop floating). Where the window first appears: bottom-right "corner" (default) or "bottom-center". */
  openFrom?: "corner" | "bottom-center";
  /** Only relevant when mode is "side_panel". Which viewport edge the panel docks to. */
  side?: "left" | "right";
  /** Only relevant when mode is "side_panel" with sidePanelMode "push". Fired on open/close so a host embed can shift its own page layout to make room. */
  onSidePanelPushChange?: (isPushed: boolean, widthPx: number, side: "left" | "right") => void;
  isAuthComponent?: boolean;
  activeElicitation?: (TElicitationEntry) | null;
  voiceAgentState?: VoiceAgentState;
  theme?: {
    background?: string;
    backgroundImage?: string;
    primary?: string;
    textColor?: "black" | "white";
    mode?: "light" | "dark";
    headerTinted?: boolean;
    hideWatermark?: boolean;
    explicitDisclaimer?: boolean;
    /** Agent-config `theme.consent_content`. Host-supplied consent/disclaimer copy; falls back to the built-in paragraphs when absent. */
    consentContent?: string | string[];
    /** Host or agent-config `theme.banner`: one line of text under the header. Colours come from the accent colour. */
    banner?: string;
  };
  feedbackModal?: {
    isOpen: boolean;
    config: AgentFeedbackConfig;
    onSubmit: (selectedValues: string[], npsScore?: number, dontShowAgain?: boolean) => Promise<void>;
    onSkip: () => void;
    onClose: () => void;
  };
  /** Upfront consent gate (agent-config `theme.upfront_consent`). */
  consentModal?: {
    isOpen: boolean;
    onAccept: () => void;
  };
}

export default function WidgetContainer({
  isOpen,
  children,
  sidebar,
  sessionDrawer,
  fullScreenEmptyState,
  sessionId,
  chatComposer,
  environment,
  mode,
  sidePanelMode,
  sidePanelWidth,
  widgetWidth = WIDGET_DIMENSIONS.width,
  widgetHeight = WIDGET_DIMENSIONS.height,
  openFrom = "corner",
  side,
  onSidePanelPushChange,
  isAuthComponent,
  activeElicitation,
  voiceAgentState,
  theme,
  feedbackModal,
  consentModal,
}: WidgetContainerProps) {
  // Header/composer chrome comes from context (provided by ChatWidget) rather
  // than ~10 pass-through props — read once here, handed to the leaves as
  // plain props so they stay props-driven.
  const {
    onClose,
    showCloseButton = true,
    title,
    titleImg,
    tagline,
    iconUrl,
    onStartNewSession,
    showStartNewChatButton,
    onToggleDisplayMode,
    onOpenSessionDrawer,
  } = useWidgetHeader();
  const [isMobile, setIsMobile] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [showDisclaimer, setShowDisclaimer] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const userLevel = useMedAssistStore((state) => state.level);

  // `mode` is the single source of truth for layout. Callers must pass the
  // resolved mode (computed by useResolvedMode) — no fallback to displayMode.
  const resolvedMode: "mobile" | "widget" | "full" | "side_panel" = mode;

  // Fullscreen mode: mode="full" — fills viewport with sidebar, no drag.
  // On mobile devices the resolver returns "mobile", so this stays false.
  const isFullScreenDesktop = resolvedMode === "full";

  // Side-panel mode: docked to a screen edge, fixed width, no drag, no sidebar.
  // On mobile devices the resolver returns "mobile", so this stays false.
  const isSidePanel = resolvedMode === "side_panel";

  // Screen-reader announcement when the user toggles between fullscreen and
  // widget. Empty on first render so we don't shout on mount.
  const previousModeRef = useRef<typeof resolvedMode | null>(null);
  const [modeAnnouncement, setModeAnnouncement] = useState("");
  useEffect(() => {
    if (previousModeRef.current !== null && previousModeRef.current !== resolvedMode) {
      setModeAnnouncement(
        resolvedMode === "full"
          ? "Switched to fullscreen mode"
          : resolvedMode === "side_panel"
            ? "Switched to side panel mode"
            : resolvedMode === "widget"
              ? "Switched to widget mode"
              : "Switched to mobile layout",
      );
    }
    previousModeRef.current = resolvedMode;
  }, [resolvedMode]);

  // Merge theme with defaults and apply it
  const mergedTheme = useMemo(() => mergeTheme(theme), [theme]);
  // Narrow selector: an identity selector (state) => state subscribes to the
  // whole store and re-renders this 900-line component on every store write.
  const setStoreMobile = useMedAssistStore((state) => state.setIsMobile);
  const isElicitationComponent = !!isAuthComponent;

  const handleElicitationSend = useCallback(async (options?: TMessageOptions) => {
    if (!chatComposer?.onSend || isSending) return;
    setIsSending(true);
    try {
      await chatComposer.onSend(options);
    } finally {
      setIsSending(false);
    }
  }, [chatComposer?.onSend, isSending]);

  // Apply theme to the container element. In fullscreen-desktop mode override
  // the base background to white (no accent tint) — matches the Figma reference
  // where the open canvas is plain white rather than the off-white widget bg.
  // Layout effect: the CSS variables must be set before the first paint,
  // otherwise every `transition-colors` element animates from the :root
  // defaults to the brand colours on mount (visible flash + non-composited
  // animations in the load trace).
  useLayoutEffect(() => {
    if (!containerRef.current) return;
    // In fullscreen-desktop, force headerTinted=false so the header uses the
    // neutral mode-appropriate bg and text (black in light, white in dark)
    // instead of the accent-tinted bg.
    const themeToApply =
      resolvedMode === "full"
        ? { ...mergedTheme, headerTinted: false }
        : mergedTheme;
    applyTheme(containerRef.current, themeToApply);
    if (resolvedMode === "full" && !mergedTheme.backgroundImage) {
      containerRef.current.style.setProperty("--background", "0 0% 100%");
      containerRef.current.style.setProperty("--widget-bg-overlay", "transparent");
    } else {
      // Clear fullscreen-only overrides when toggling back to widget mode so
      // applyTheme's values (tinted bg) take effect again.
      containerRef.current.style.removeProperty("--background");
      containerRef.current.style.removeProperty("--widget-bg-overlay");
      applyTheme(containerRef.current, mergedTheme);
    }
  }, [mergedTheme, resolvedMode]);

  useEffect(() => {
    const checkMobile = () => {
      const width = window?.innerWidth ?? 0;
      const userAgent = navigator?.userAgent?.toLowerCase() ?? "";
      // Mobile is layout-only here — `mode` already encodes the resolved
      // device-vs-preference decision upstream (useResolvedMode). This
      // local detector only drives the imperative visual-viewport effect
      // (keyboard handling) which depends on actually being on a mobile
      // device, not just a "full" preference on a wide viewport.
      const layoutIsMobile =
        width < 768 ||
        /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(
          userAgent
        );

      setIsMobile(layoutIsMobile);
      setStoreMobile(layoutIsMobile);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Handle visual viewport changes (keyboard appearing/disappearing).
  // useLayoutEffect so cleanup (which clears imperatively-set inline width/
  // height) runs *before* downstream layout-effect measurements (e.g. the
  // useDraggable init that reads offsetWidth/offsetHeight on mode toggle).
  useLayoutEffect(() => {
    if (!isOpen || !isMobile || !containerRef.current) return;

    const container = containerRef.current;
    let rafId: number | null = null;
    let resizeTimeout: ReturnType<typeof setTimeout> | null = null;
    let scrollTopReenableTimeout: ReturnType<typeof setTimeout> | null = null;
    let lastViewportTop = window.visualViewport?.offsetTop ?? 0;
    let lastScrollUpdateAt = 0;
    const VIEWPORT_TOP_EPSILON_PX = 2;
    const MIN_SCROLL_UPDATE_MS = 80;

    // Use Visual Viewport API if available for better keyboard handling
    if (window.visualViewport) {
      const updateViewport = () => {
        if (container && window.visualViewport) {
          const viewportHeight = window.visualViewport.height;
          const viewportTop = window.visualViewport.offsetTop;

          // Use requestAnimationFrame for smooth updates
          rafId = requestAnimationFrame(() => {
            // Ensure container covers the full visible viewport
            container.style.transition = "none"; // Disable transitions during viewport changes
            container.style.top = `${viewportTop}px`;
            container.style.left = "0";
            container.style.right = "0";
            container.style.bottom = "auto";
            container.style.width = "100vw";
            container.style.height = `${viewportHeight}px`;
            container.style.maxHeight = `${viewportHeight}px`;
            container.style.minHeight = `${viewportHeight}px`; // Prevent shrinking too much

            // Re-enable transitions after a brief delay
            if (resizeTimeout) clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
              container.style.transition = "";
            }, 100);
          });
        }
      };

      const handleResize = () => {
        updateViewport();
      };

      const handleScroll = () => {
        if (!container || !window.visualViewport) return;

        const viewportTop = window.visualViewport.offsetTop;
        const now = Date.now();

        // On Android, focusing OTP inputs can cause frequent visualViewport scroll
        // events with very small offsetTop deltas. Updating the container top
        // for every such event causes the whole widget to "jitter".
        if (Math.abs(viewportTop - lastViewportTop) < VIEWPORT_TOP_EPSILON_PX) return;
        if (now - lastScrollUpdateAt < MIN_SCROLL_UPDATE_MS) return;

        lastScrollUpdateAt = now;
        lastViewportTop = viewportTop;

        rafId = requestAnimationFrame(() => {
          container.style.transition = "none";
          container.style.top = `${viewportTop}px`;

          if (scrollTopReenableTimeout) clearTimeout(scrollTopReenableTimeout);
          scrollTopReenableTimeout = setTimeout(() => {
            container.style.transition = "";
          }, 150);
        });
      };

      window.visualViewport.addEventListener("resize", handleResize);
      window.visualViewport.addEventListener("scroll", handleScroll);

      // Set initial height and position
      updateViewport();

      return () => {
        if (rafId) cancelAnimationFrame(rafId);
        if (resizeTimeout) clearTimeout(resizeTimeout);
        if (scrollTopReenableTimeout) clearTimeout(scrollTopReenableTimeout);
        window.visualViewport?.removeEventListener("resize", handleResize);
        window.visualViewport?.removeEventListener("scroll", handleScroll);
        // Only clear inline styles that React's style prop does not own.
        // width/height/maxHeight are React-owned in every mode (the floating
        // size is inline, not a class) and React has already written the new
        // mode's values by the time this cleanup runs — clearing them here
        // would leave the floating widget content-sized after a mobile ->
        // desktop resize. top/left/right/bottom are React-owned too (drag position).
        if (container) {
          container.style.minHeight = "";
          container.style.transition = "";
        }
      };
    } else {
      // Fallback for browsers without Visual Viewport API
      const handleResize = () => {
        if (container) {
          container.style.transition = "none";
          container.style.top = "0";
          container.style.left = "0";
          container.style.right = "0";
          container.style.bottom = "auto";
          container.style.width = "100vw";
          container.style.height = "100svh";
          container.style.maxHeight = "100svh";
          setTimeout(() => {
            container.style.transition = "";
          }, 100);
        }
      };

      window.addEventListener("resize", handleResize);
      handleResize();

      return () => {
        window.removeEventListener("resize", handleResize);
        // width/height/maxHeight are React-owned — see the cleanup above.
        if (container) {
          container.style.transition = "";
        }
      };
    }
  }, [isOpen, isMobile]);

  // Lock body scroll when widget is open to prevent background scrolling.
  // iOS Safari ignores overflow:hidden on body — position:fixed is required.
  // Additionally, iOS lets the viewport scroll when the keyboard is open,
  // so we intercept touch events to block that.
  useEffect(() => {
    // Side-panel push mode is meant to be used alongside the still-visible,
    // narrowed host page — locking body scroll would contradict that. Overlay
    // sub-mode (and every other mode) keeps the existing scroll-lock behavior.
    if (isOpen && !(isSidePanel && sidePanelMode === "push")) {
      const container = containerRef.current;
      const scrollY = window.scrollY;
      const originalBodyStyle = document.body.style.cssText;
      const originalHtmlOverflow = document.documentElement.style.overflow;

      // Calculate scrollbar width to prevent layout shift
      const scrollbarWidth =
        window.innerWidth - document.documentElement.clientWidth;

      document.body.style.position = "fixed";
      document.body.style.top = `-${scrollY}px`;
      document.body.style.left = "0";
      document.body.style.right = "0";
      document.body.style.width = "100%";
      document.body.style.overflow = "hidden";
      document.documentElement.style.overflow = "hidden";

      if (scrollbarWidth > 0 && !isMobile) {
        document.body.style.paddingRight = `${scrollbarWidth}px`;
      }

      let lastTouchY = 0;

      const onTouchStart = (e: TouchEvent) => {
        lastTouchY = e.touches[0].clientY;
      };

      const onTouchMove = (e: TouchEvent) => {
        if (e.touches.length !== 1) return;
        const deltaY = lastTouchY - e.touches[0].clientY;
        lastTouchY = e.touches[0].clientY;

        let el = e.target as HTMLElement | null;
        while (el && el !== container) {
          const { overflowY } = window.getComputedStyle(el);
          if (
            (overflowY === "auto" || overflowY === "scroll") &&
            el.scrollHeight > el.clientHeight
          ) {
            const { scrollTop, scrollHeight, clientHeight } = el;
            const atTop = scrollTop <= 0 && deltaY < 0;
            const atBottom = scrollTop + clientHeight >= scrollHeight - 1 && deltaY > 0;
            if (!atTop && !atBottom) return; // within bounds — allow
            break;
          }
          el = el.parentElement;
        }
        e.preventDefault();
      };

      if (container) {
        container.addEventListener("touchstart", onTouchStart, { passive: true });
        container.addEventListener("touchmove", onTouchMove, { passive: false });
      }

      return () => {
        if (container) {
          container.removeEventListener("touchstart", onTouchStart);
          container.removeEventListener("touchmove", onTouchMove);
        }
        document.body.style.cssText = originalBodyStyle;
        document.documentElement.style.overflow = originalHtmlOverflow;
        window.scrollTo(0, scrollY);
      };
    }
  }, [isOpen, isMobile, isSidePanel, sidePanelMode]);

  // Signal open/close (and width/side) to the host embed loader, which owns
  // the actual host-document mutation — this React tree runs inside a Shadow
  // DOM and can never itself resize the host's real <body>. Effect cleanup
  // fires synchronously on unmount, so closing the widget reliably reverts
  // the push with no bespoke close-handling needed in the loader.
  // Only register the revert cleanup when this run actually pushed: the widget
  // mounts with isOpen=false and flips it in a mount effect, and a cleanup
  // registered on that first (non-pushing) run would fire a spurious
  // "un-push" to the host right before the real push.
  useEffect(() => {
    if (!isSidePanel || sidePanelMode !== "push" || !isOpen) return;
    onSidePanelPushChange?.(true, sidePanelWidth ?? 0, side ?? "right");
    return () => {
      onSidePanelPushChange?.(false, sidePanelWidth ?? 0, side ?? "right");
    };
  }, [isOpen, isSidePanel, sidePanelMode, sidePanelWidth, side, onSidePanelPushChange]);

  const { position: dragPosition, elementRef: dragRef } = useDraggable({
    enabled: isOpen && !isMobile && !isFullScreenDesktop && !isSidePanel,
    size: { width: widgetWidth, height: widgetHeight },
    anchor: openFrom === "bottom-center" ? "bottom-center" : "bottom-right",
  })

  //merge refs
  useEffect(() => {
    if (containerRef.current) {
      dragRef.current = containerRef.current;
    }
  }, [dragRef])

  // Single isolated container for the entire widget
  const containerStyles = cn(
    // Base isolation styles - prevents host website interference
    "synapse-chat-widget-container",
    "fixed m-0 p-0",
    "box-border",
    // Only apply transition for desktop widget, disable for mobile/fullscreen to prevent flickering
    !isMobile && !isFullScreenDesktop && !isSidePanel ? "transition-all duration-300" : "",
    // Positioning
    isMobile
      ? "w-screen h-[100svh]"
      : isFullScreenDesktop
        ? "w-screen h-screen"
        : isSidePanel
          // Width is dynamic (sidePanelWidth), set via inline style below.
          ? "h-screen"
          // Floating: width/height are dynamic (widgetWidth/widgetHeight), set via inline style below.
          : "",
    // Z-index - highest possible
    "z-[2147483647]",
    // Visibility
    isOpen
      ? "opacity-100 pointer-events-auto"
      : "opacity-0 pointer-events-none scale-95"
  );


  const cardStyles = cn(
    "w-full h-full relative",
    "bg-background",
    "shadow-2xl",
    "flex",
    "overflow-hidden",
    mergedTheme.backgroundImage ? "theme-with-background" : "",
    isMobile
      ? "rounded-none border-0 flex-col"
      : isFullScreenDesktop
        ? "rounded-none border-0 flex-row"
        : isSidePanel
          ? "rounded-none border-0 flex-col"
          : "rounded-3xl flex-col"
  );

  return (
    <div
      ref={containerRef}
      data-mode={resolvedMode}
      className={containerStyles}
      style={{
        // Reset only essential properties that might interfere
        margin: 0,
        padding: 0,
        border: "none",
        outline: "none",
        // Ensure proper stacking and positioning
        position: "fixed",
        zIndex: 2147483647,
        // fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji'",
        fontSize: "16px",
        lineHeight: "2.5",
        // Prevent text selection issues from host
        userSelect: "auto",
        // Fullscreen desktop: fill viewport edge-to-edge — only when open.
        // When closed, skipping these styles + display:none below ensures the
        // (invisible) shell doesn't sit over the launcher button.
        ...(isFullScreenDesktop && isOpen && {
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          width: "100vw",
          height: "100vh",
        }),
        // Hard-hide the shell when closed in fullscreen so its 100vw/100vh
        // pointer-events-none layer (still positioned at top:0/left:0 even
        // with opacity-0) cannot occlude the launcher button.
        ...(isFullScreenDesktop && !isOpen && { display: "none" }),
        // Side panel: docked to a screen edge, full height, fixed width —
        // only when open. Same "hard-hide when closed" trick as fullscreen so
        // the shell can't occlude the launcher.
        ...(isSidePanel && isOpen && {
          top: 0,
          bottom: 0,
          [side === "left" ? "left" : "right"]: 0,
          [side === "left" ? "right" : "left"]: "auto",
          width: `${sidePanelWidth}px`,
          height: "100vh",
        }),
        ...(isSidePanel && !isOpen && { display: "none" }),
        // Draggable position for desktop widget (not mobile, not fullscreen, not side panel)
        ...(!isMobile && !isFullScreenDesktop && !isSidePanel && {
          left: `${dragPosition.x}px`,
          top: `${dragPosition.y}px`,
          bottom: "auto",
          right: "auto",
          // Configured size, capped so it never outgrows a small viewport.
          width: `${widgetWidth}px`,
          height: `${widgetHeight}px`,
          maxWidth: `calc(100vw - ${2 * WIDGET_VIEWPORT_PADDING}px)`,
          maxHeight: `calc(100vh - ${2 * WIDGET_VIEWPORT_PADDING}px)`,
        }),
        // For mobile: ensure container respects visual viewport when keyboard appears
        // These will be overridden by Visual Viewport API if available
        ...(isMobile && {
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          width: "100vw",
          maxHeight: "100svh",
          height: "100svh",
          backgroundColor: mergedTheme.backgroundImage ? "transparent" : "hsl(var(--background))",
        }),
        // Ensure proper font rendering
        // WebkitFontSmoothing: "antialiased",
        // MozOsxFontSmoothing: "grayscale",
      }}>
      <style>{`
        /* Isolate widget from host website styles */
        .synapse-chat-widget-container,
        .synapse-chat-widget-container *,
        .synapse-chat-widget-container *::before,
        .synapse-chat-widget-container *::after {
          box-sizing: border-box;
        }
        .synapse-chat-widget-container {
          /* isolation: isolate; */
          /* Reset common host website interferences */
          text-align: left;
          text-decoration: none;
          list-style: none;
          /* Ensure no margin/padding from host */
          margin: 0 !important;
          padding: 0 !important;
        }
        /* Handle mobile keyboard viewport adjustments */
        @supports (height: 100svh) {
          .synapse-chat-widget-container {
            /* Use visual viewport height when keyboard appears */
            max-height: 100svh;
          }
        }
        /* Prevent viewport jumping on mobile */
        @media (max-width: 768px) {
          .synapse-chat-widget-container {
            /* Use safe area insets for better mobile support */
            height: 100svh;
            max-height: 100svh;
          }
        }
        /* Prevent scroll chaining from chat scroll area to body (iOS) */
        .synapse-chat-widget-container [data-radix-scroll-area-viewport] {
          overscroll-behavior: contain;
        }
      `}</style>
      <Card
        className={cardStyles}
        data-text-color={mergedTheme.textColor}
        style={!isMobile ? { border: "1.5px solid hsl(var(--primary) / 0.5)" } : undefined}
      >
        {/* Mode-change announcement for screen readers (visually hidden). */}
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            padding: 0,
            margin: -1,
            overflow: "hidden",
            clip: "rect(0,0,0,0)",
            whiteSpace: "nowrap",
            border: 0,
          }}
        >
          {modeAnnouncement}
        </div>
        {/* Accent color tint overlay on base background */}
        {!mergedTheme.backgroundImage && (
          <div
            className="absolute inset-0 pointer-events-none"
            style={{ backgroundColor: "var(--widget-bg-overlay)" }}
          />
        )}
        {/* Background image overlay with blur */}
        {mergedTheme.backgroundImage && (
          <div
            className="absolute inset-0 -z-10"
            style={{
              backgroundImage: `url(${mergedTheme.backgroundImage})`,
              backgroundSize: 'cover',
              backgroundPosition: 'center',
              backgroundRepeat: 'no-repeat',
              // filter: `blur(3px)`,
              transform: 'scale(1.1)', // Scale up to cover blur edges
            }}
          />
        )}
        {mergedTheme.backgroundImage && (
          <div
            className="absolute inset-0 -z-10"
            style={{
              backgroundColor:
                mergedTheme.textColor === "white"
                  ? "rgba(0, 0, 0, 0.4)"
                  : "rgba(255, 255, 255, 0.4)",
            }}
          />
        )}
        {/* Modals — at Card level so absolute inset-0 covers header + footer.
            z-[60] beats the sticky header/footer's z-50. */}
        <DisclaimerModal
          isOpen={showDisclaimer}
          onClose={() => setShowDisclaimer(false)}
          botName={title}
          explicitDisclaimer={theme?.explicitDisclaimer}
          consentContent={theme?.consentContent}
          isFullScreen={isFullScreenDesktop}
        />
        {/* Consent gate sits above the disclaimer/feedback modals in source
            order only — they never coexist: consent shows on first open,
            before there is a chat to give feedback on or a footer to tap. */}
        {consentModal?.isOpen && (
          <ConsentModal
            isOpen
            botName={title}
            consentContent={theme?.consentContent}
            onAccept={consentModal.onAccept}
            isFullScreen={isFullScreenDesktop}
          />
        )}
        {feedbackModal?.isOpen && (
          <Suspense fallback={null}>
            <FeedbackModal
              isOpen={feedbackModal.isOpen}
              config={feedbackModal.config}
              onSubmit={feedbackModal.onSubmit}
              onSkip={feedbackModal.onSkip}
              onClose={feedbackModal.onClose}
            />
          </Suspense>
        )}

        {/* Sidebar — only in fullscreen desktop mode */}
        {isFullScreenDesktop && sidebar}

        {/* Session drawer overlay — the fullscreen sidebar replaces it, so it
            only mounts in widget/mobile layouts. */}
        {userLevel === "user" && !isFullScreenDesktop && sessionDrawer}

        {/* Main chat column */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 h-full">
          <div className="flex-shrink-0 sticky top-0 z-50 synapse-chat-widget-header" style={{
            // Same trick as the footer — solid bg layer + translucent overlay,
            // so chat content scrolling under the sticky header is hidden.
            ...(isFullScreenDesktop
              ? { background: "transparent" }
              : {
                backgroundColor: "hsl(var(--background))",
                backgroundImage:
                  "linear-gradient(var(--header-bg), var(--header-bg))",
              }),
            borderBottom: "0.5px solid var(--header-stroke)",
            ...(!isMobile && !isFullScreenDesktop && !isSidePanel && {
              cursor: isOpen ? "grab" : "default",
            }),
          }}>
            <ProfileHeader
              onClose={onClose}
              showCloseButton={showCloseButton}
              title={title}
              titleImg={titleImg}
              tagline={tagline}
              iconUrl={iconUrl}
              startNewConversation={onStartNewSession}
              voiceAgentState={voiceAgentState}
              headerTinted={isFullScreenDesktop ? false : mergedTheme.headerTinted}
              onToggleDisplayMode={onToggleDisplayMode}
              // Fullscreen surfaces chat history in the left sidebar, so the
              // header's history affordance would be a duplicate — dropping
              // the callback is what hides it.
              onOpenSessionDrawer={isFullScreenDesktop ? undefined : onOpenSessionDrawer}
            />
          </div>
          {theme?.banner?.trim() && <HeaderBanner text={theme.banner.trim()} />}
          {(() => {
            // Build the composer node once, render it either inline (centered
            // inside the empty-state stack on fullscreen) or in the footer.
            // Inline (empty-state) keeps the original pill layout; only the
            // footer composer in fullscreen-chat uses the Figma stacked layout.
            const inlineComposerMode = isFullScreenDesktop && !!fullScreenEmptyState;
            const composerNode = chatComposer && voiceAgentState === VOICE_AGENT_STATE.IDLE ? (
              <Suspense fallback={<ComposerSkeleton />}>
                <ChatComposer
                  value={chatComposer.value}
                  onChange={chatComposer.onChange}
                  onSend={isElicitationComponent ? handleElicitationSend : chatComposer.onSend}
                  onFileChange={chatComposer.onFileChange}
                  onRemoveFile={chatComposer.onRemoveFile}
                  onRecording={chatComposer.onRecording}
                  isRecording={chatComposer.isRecording}
                  hasAttachment={chatComposer.hasAttachment}
                  attachmentFiles={chatComposer.attachmentFiles}
                  isDisabled={chatComposer.isDisabled || (isElicitationComponent && isSending)}
                  isMobile={isMobile}
                  placeholder={chatComposer.placeholder}
                  recordingStatus={chatComposer.recordingStatus}
                  theme={mergedTheme}
                  onStartNewChat={onStartNewSession}
                  showStartNewChatButton={showStartNewChatButton}
                  isVoiceAgentActive={chatComposer.isVoiceAgentActive}
                  handleVoiceMode={chatComposer.handleVoiceMode}
                  allowed={chatComposer.allowed}
                  isAuthComponent={isAuthComponent}
                  activeElicitationState={activeElicitation}
                  isFullScreen={isFullScreenDesktop && !inlineComposerMode}
                  showAttention={chatComposer.showAttention}
                />
              </Suspense>
            ) : null;

            const brandingFontStyle = {
              fontFamily: "Inter, system-ui, -apple-system, sans-serif",
              fontWeight: 400,
              fontStyle: "normal",
              letterSpacing: "0%",
            } as const;

            const brandingFooter = (
              <>
                {sessionId && environment === "development" && (
                  <div className="px-6 flex justify-center items-center">
                    <p className="text-[8px] text-text-secondary font-mono opacity-50">
                      Session ID: {sessionId}
                    </p>
                  </div>
                )}
                {isFullScreenDesktop ? (
                  // Fullscreen desktop always shows the full explicit disclaimer
                  // text (Figma reply-box footer) instead of the "Powered by"
                  // watermark — there's room for it and no floating-widget chrome.
                  // hideWatermark has no bearing here since there's no "Powered by
                  // Eka Care" text in this variant to begin with.
                  <div
                    onClick={() => setShowDisclaimer(true)}
                    className="px-6 py-1 flex justify-center items-center text-center text-foreground opacity-50 hover:opacity-70 transition-opacity cursor-pointer bg-transparent border-none rounded"
                    aria-label="Open disclaimer"
                  >
                    <span className="text-[10px] leading-[14px]" style={brandingFontStyle}>
                      This is an AI chatbot and can make mistake. Please double check responses.{" "}
                      <span className="underline underline-offset-2">Terms &amp; privacy</span>
                    </span>
                  </div>
                ) : theme?.explicitDisclaimer ? (
                  <div
                    onClick={() => setShowDisclaimer(true)}
                    className="px-6 py-1 flex flex-col justify-center items-center gap-0.5 text-foreground opacity-50 hover:opacity-70 transition-opacity cursor-pointer bg-transparent border-none rounded"
                    aria-label="Open disclaimer"
                  >
                    {theme?.hideWatermark !== true && (
                      <div className="flex justify-center items-center gap-1">
                        <span className="text-[10px] leading-[14px]" style={brandingFontStyle}>
                          Powered by
                        </span>
                        <span className="text-[10px] leading-[14px]" style={brandingFontStyle}>
                          Eka Care
                        </span>
                      </div>
                    )}
                    <span className="text-[10px] leading-[14px]" style={brandingFontStyle}>
                      AI can make mistakes. <span className="underline underline-offset-2">Terms &amp; privacy</span>
                    </span>
                  </div>
                ) : (
                  <div
                    onClick={() => setShowDisclaimer(true)}
                    className="px-6 py-1 flex justify-center items-center gap-1 text-foreground opacity-50 hover:opacity-70 transition-opacity cursor-pointer bg-transparent border-none rounded"
                    aria-label="Open disclaimer"
                  >
                    {theme?.hideWatermark !== true && (
                      <>
                        <span className="text-[10px] leading-[14px]" style={brandingFontStyle}>
                          Powered by
                        </span>
                        <span className="text-[10px] leading-[14px]" style={brandingFontStyle}>
                          Eka Care
                        </span>
                      </>
                    )}
                    <Info className="w-3 h-3" />
                  </div>
                )}
              </>
            );

            // Render-prop slot fill: when the host supplied an empty state and
            // we're in inline-composer mode, hand it the composer + branding
            // nodes built locally above.
            const renderedEmptyState =
              fullScreenEmptyState && isFullScreenDesktop
                ? fullScreenEmptyState({
                  composer: inlineComposerMode ? composerNode : null,
                  composerFooter: inlineComposerMode ? brandingFooter : null,
                })
                : null;

            return (
              <>
                <div className="flex-1 min-h-0 overflow-hidden flex flex-col relative">
                  {renderedEmptyState ?? children}
                  {/* Toast overlay lives here (not inside children) so it renders
                      over the empty-state view too — warnings arrive while the
                      chat is still empty. */}
                  <DispToastHost />
                </div>
                {chatComposer && !inlineComposerMode && (
                  <div
                    className={cn(
                      "flex-shrink-0 sticky bottom-0 z-50"
                    )}
                    style={{
                      // Layer a SOLID background under the translucent footer-bg
                      // overlay so chat content scrolling underneath the sticky
                      // footer doesn't bleed through. Without this, --footer-bg
                      // (rgba 255,255,255,0.7) lets messages show through.
                      // backgroundColor: "hsl(var(--background))",
                      // backgroundImage:
                      //   "linear-gradient(var(--footer-bg), var(--footer-bg))",
                      // // Fullscreen uses the Figma reply-box card, which already has
                      // // its own border — drop the divider above it.
                      // borderTop: isFullScreenDesktop
                      //   ? "none"
                      //   : "0.5px solid var(--footer-stroke)",
                    }}
                  >
                    {/* Center the composer in fullscreen mode so it lines up
                        with the centered messages above. */}
                    <div className={cn(isFullScreenDesktop && "max-w-2xl mx-auto w-full")}>
                      {composerNode}
                    </div>
                    {brandingFooter}
                  </div>
                )}
                {/* In inline (fullscreen empty-state) mode the branding is
                    rendered inside the composer card via composerFooter. */}
              </>
            );
          })()}
        </div>
      </Card>
    </div>
  );
}