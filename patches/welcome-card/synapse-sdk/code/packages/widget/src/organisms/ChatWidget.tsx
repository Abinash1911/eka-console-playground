import { lazy, Suspense, useEffect, useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { ChevronDown } from "lucide-react";
import { cn } from "../lib/utils";
import WidgetContainer from "./WidgetContainer";
const VoiceAgentScreen = lazy(() => import("@/molecules/voice/VoiceAgentScreen"));
// Only hosts that set `theme.welcomeCard` ever load it.
const WelcomeCard = lazy(() => import("@/molecules/banner/WelcomeCard"));
import SessionList from "@/molecules/sidebar/SessionList";
import EmptyStateFullScreen from "@/molecules/chat/EmptyStateFullScreen";
import { SessionTranscriptSkeleton } from "@/atoms/Skeleton";
import { useChatWidget, type UseChatWidgetConfig } from "@/hooks/useChatWidget";

import ChatMessages from "@/molecules/chat/ChatMessages";
import { ResizeProvider } from "@/context/ResizeContext";
import { WidgetHeaderProvider, type TWidgetHeaderConfig } from "@/context/WidgetHeaderContext";

// First-paint-critical: always mounted on open, so import statically and let
// them ride in the main chunk — avoids the dynamic-import round-trip waterfall.
// (VoiceAgentScreen stays lazy: voice-mode only.)
import { ConnectionStatus as ConnectionStatusBanner } from "../molecules/connection/ConnectionStatus";

interface ChatWidgetProps {
  isOpen: boolean;
  agentId: string;
  config: UseChatWidgetConfig;
}

export default function ChatWidget({
  isOpen,
  agentId,
  config,
}: ChatWidgetProps) {
  const {
    hasUserMessage,
    toggleDisplayMode,
    resolvedMode,
    scrollAreaRef,
    messagesEndRef,
    showScrollButton,
    isRestoring,
    startNewConnection,
    showRetryButton,
    clearError,
    error,
    sessionId,
    activeElicitation,
    isAuthComponent,
    isConnected,
    inConversation,
    isFirstMessage,
    isEmptyChat,
    isLoadingSessionMessages,
    initialMessage,
    incomingMessages,
    sendMessageFeedback,
    clearElicitationState,
    handleRetry,
    scrollToBottom,
    chatComposerProps,
    isComposerDisabled,
    voiceAgentState,
    isMuted,
    isVoiceAgentActive,
    disconnectVoiceAgent,
    resetVoiceAgent,
    toggleMute,
    handleClose,
    isSessionDrawerOpen,
    pastSessions,
    isLoadingPastSessions,
    openSessionDrawer,
    closeSessionDrawer,
    userLevel,
    isSidebarCollapsed,
    toggleSidebar,
    feedbackModalProps,
    waitingTips,
    consentModalProps,
    handleChatSendMessage,
    handleEmptyStateSendMessage,
    handleSelectSession,
    handleStartNewChat,
    sidePanelMode,
    sidePanelWidth,
    widgetWidth,
    widgetHeight,
    openFrom,
    side,
    onSidePanelPushChange,
  } = useChatWidget({ isOpen, agentId, config });

  // When the chat is cleared (new session), useScrollManagement's message-count
  // effect exits early (messageCount === 0) and won't scroll. Snap to bottom
  // here so the InitialMessageView isn't hidden by a stale scroll position.
  useEffect(() => {
    if (!incomingMessages.length) scrollToBottom("auto");
  }, [incomingMessages.length, scrollToBottom]);

  // Section divider timestamp. Computed once at mount instead of on every
  // render: toLocaleString() is ~7ms and ChatWidget re-renders on each stream
  // chunk, so recomputing it dominated the early render path.
  const sectionTimestamp = useMemo(
    () =>
      new Date().toLocaleString("en-US", {
        weekday: "long",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true,
      }),
    []
  );

  // Fullscreen session rail. Visibility follows the *resolved* mode (live), not
  // the static config, so the resize toggle shows/hides it at runtime. Gated on
  // the logged-in level for the same reason the drawer is — guests have no
  // server-side session history to list. Memoized elements: React bails out of
  // re-rendering a child when it receives the exact same element again, so the
  // session lists don't re-render on every stream chunk.
  const sidebarElement = useMemo(
    () =>
      resolvedMode === "full" && userLevel === "user" ? (
        <SessionList
          variant="sidebar"
          sessions={pastSessions}
          activeSessionId={sessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleStartNewChat}
          isCollapsed={isSidebarCollapsed}
          onToggle={toggleSidebar}
          isLoading={isLoadingPastSessions}
        />
      ) : undefined,
    [resolvedMode, userLevel, pastSessions, sessionId, handleSelectSession, handleStartNewChat, isSidebarCollapsed, toggleSidebar, isLoadingPastSessions]
  );

  // One props object for the two ConnectionStatusBanner instances (empty-state
  // and chat footer) so they can't drift apart.
  const welcomeCardConfig = config.theme?.welcomeCard;
  const welcomeCardNode =
    welcomeCardConfig?.title?.trim() && !hasUserMessage && !isLoadingSessionMessages ? (
      <Suspense fallback={null}>
        <WelcomeCard config={welcomeCardConfig} />
      </Suspense>
    ) : null;

  const connectionBannerProps = useMemo(() => ({
    onRetry: handleRetry,
    showRetryButton,
    startNewConnection,
    clearError,
    error,
    isConnected,
  }), [handleRetry, showRetryButton, startNewConnection, clearError, error, isConnected]);

  // Header/composer config — delivered via context so WidgetContainer no
  // longer carries ~10 props whose only purpose was to reach ProfileHeader
  // and ChatComposer (see WidgetHeaderContext).
  const headerConfig = useMemo<TWidgetHeaderConfig>(() => ({
    onClose: handleClose,
    showCloseButton: config.showCloseButton,
    title: config.title,
    titleImg: config.theme?.titleImg,
    tagline: config.theme?.tagline,
    iconUrl: config.iconUrl,
    onStartNewSession: handleStartNewChat,
    showStartNewChatButton: startNewConnection,
    onToggleDisplayMode: config.resize ? toggleDisplayMode : undefined,
    onOpenSessionDrawer: openSessionDrawer,
  }), [
    handleClose,
    config.showCloseButton,
    config.title,
    config.theme?.titleImg,
    config.theme?.tagline,
    config.iconUrl,
    handleStartNewChat,
    startNewConnection,
    config.resize,
    toggleDisplayMode,
    openSessionDrawer,
  ]);

  const sessionDrawerElement = useMemo(
    () => (
      <SessionList
        variant="drawer"
        isOpen={isSessionDrawerOpen}
        onClose={closeSessionDrawer}
        sessions={pastSessions}
        activeSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleStartNewChat}
        isLoading={isLoadingPastSessions}
      />
    ),
    [isSessionDrawerOpen, closeSessionDrawer, pastSessions, sessionId, handleSelectSession, handleStartNewChat, isLoadingPastSessions]
  );

  return (
    <ResizeProvider enabled={!!config.resize}>
      <WidgetHeaderProvider value={headerConfig}>
      <WidgetContainer
        isOpen={isOpen}
        feedbackModal={feedbackModalProps}
        consentModal={consentModalProps}
        sessionId={sessionId}
        environment={config.environment}
        mode={resolvedMode}
        sidePanelMode={sidePanelMode}
        sidePanelWidth={sidePanelWidth}
        widgetWidth={widgetWidth}
        widgetHeight={widgetHeight}
        openFrom={openFrom}
        side={side}
        onSidePanelPushChange={onSidePanelPushChange}
        theme={config.theme}
        isAuthComponent={isAuthComponent}
        activeElicitation={activeElicitation}
        voiceAgentState={voiceAgentState}
        chatComposer={chatComposerProps}
        sessionDrawer={sessionDrawerElement}
        sidebar={sidebarElement}
        fullScreenEmptyState={
          isEmptyChat
            ? (slots) => (
              <EmptyStateFullScreen
                title={config.title}
                description={initialMessage?.text}
                suggestions={initialMessage?.suggestions}
                onSendMessage={handleEmptyStateSendMessage}
                disabled={isComposerDisabled}
                composer={slots.composer}
                composerFooter={slots.composerFooter}
                connectionBanner={<ConnectionStatusBanner {...connectionBannerProps} />}
                welcomeCard={welcomeCardNode}
              />
            )
            : undefined
        }>
        {isVoiceAgentActive ? (
          <Suspense fallback={<WidgetContentFallback />}>
            <VoiceAgentScreen
              state={voiceAgentState}
              isMuted={isMuted}
              onEndCall={disconnectVoiceAgent}
              onClose={resetVoiceAgent}
              onToggleMute={toggleMute}
              agentName={config.title}
              iconUrl={config.iconUrl}
              textColor={config.theme?.textColor}
            />
          </Suspense>
        ) : (<Suspense fallback={<WidgetContentFallback />}>
          <div className={cn("flex-1 flex flex-col min-h-0 overflow-hidden relative synapse-chat-window")}>
            <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
              {/* Reopened long chat: shimmer while it settles at the bottom,
                  instead of showing it scroll through the whole history. */}
              {isRestoring && (
                <div
                  className={cn(
                    "absolute inset-0 z-[1] flex flex-col justify-end overflow-hidden px-4 pb-3 pointer-events-none",
                    resolvedMode === "full" && "max-w-2xl mx-auto w-full",
                  )}>
                  <SessionTranscriptSkeleton />
                </div>
              )}
              <ScrollArea
                ref={scrollAreaRef}
                aria-busy={isRestoring || undefined}
                className={cn(
                  "flex-1 min-h-0 [&>[data-radix-scroll-area-viewport]>div]:!flex [&>[data-radix-scroll-area-viewport]>div]:flex-col [&>[data-radix-scroll-area-viewport]>div]:min-h-full",
                  // invisible, not unmounted: it must keep its layout so the
                  // restore can measure and pin it to the bottom.
                  isRestoring ? "invisible" : "motion-safe:animate-in motion-safe:fade-in-0 duration-150",
                )}
              >
                {/* Spacer pushes content to bottom when it fits, collapses when content overflows */}
                <div className="flex-1" />
                <div
                  className={cn(
                    "min-w-0 overflow-x-hidden",
                    inConversation ? "pt-4 px-4 space-y-3" : "pt-4 px-4 space-y-4",
                    // Center the chat content in fullscreen so messages don't
                    // sprawl across the whole viewport — mirrors the Figma layout.
                    resolvedMode === "full" && "max-w-2xl mx-auto w-full",
                  )}>

                  {/* Loading a past session's transcript: shimmer the bubbles
                      instead of the timestamp + empty message list, which would
                      otherwise read as "this chat has no messages". */}
                  {isLoadingSessionMessages ? (
                    <SessionTranscriptSkeleton />
                  ) : (
                    <>
                      {welcomeCardNode}
                      {isFirstMessage && (
                        <div className="text-xs text-[var(--color-muted-foreground)] text-center mb-2">
                          Just now
                        </div>
                      )}

                      {!isFirstMessage && (
                        <div className="text-xs text-[var(--color-muted-foreground)] text-center">
                          {sectionTimestamp}
                        </div>
                      )}
                      <ChatMessages
                        messages={incomingMessages}
                        onSendMessage={handleChatSendMessage}
                        onToggleFeedback={sendMessageFeedback}
                        onClearElicitationState={clearElicitationState}
                        isAuthComponent={isAuthComponent}
                        isFullScreen={resolvedMode === "full"}
                        initialMessage={initialMessage ?? undefined}
                        disabled={!isConnected}
                        waitingTips={waitingTips}
                      />
                    </>
                  )}
                  <div ref={messagesEndRef} />
                </div>
              </ScrollArea>
            </div>

            {/* Floating scroll to bottom button */}
            {showScrollButton && (
              <div className="absolute bottom-[10px] left-1/2 transform -translate-x-1/2 z-10">
                <Button
                  onClick={() => scrollToBottom("smooth")}
                  size="icon"
                  className="h-10 w-10 rounded-full bg-surface/90 backdrop-blur-sm shadow-lg border border-border-subtle hover:bg-surface hover:shadow-xl transition-all duration-200">
                  <ChevronDown className="w-5 h-5 text-text-primary" />
                </Button>
              </div>
            )}

            <ConnectionStatusBanner className="mt-2" {...connectionBannerProps} />
          </div>
        </Suspense>
        )}
      </WidgetContainer>
      </WidgetHeaderProvider>
    </ResizeProvider>
  );
}


function WidgetContentFallback() {
  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-surface backdrop-blur-2xl animate-pulse">
      <div className="flex-1 p-6 space-y-4">
        <div className="h-16 bg-surface/80 rounded-2xl border border-border-subtle/50" />
        <div className="h-16 bg-surface/80 rounded-2xl border border-border-subtle/50" />
        <div className="h-16 bg-surface/80 rounded-2xl border border-border-subtle/50" />
      </div>
      <div className="h-24 border-t border-border-subtle bg-surface/80" />
    </div>
  );
}
