import { useCallback, useMemo, useState } from "react";

// Same per-agent store as the feedback / consent "ask once" flags in useChatWidget.
const AGENT_CONFIG_CACHE_KEY = "eka-medassist-agent-config";

function readFlag(agentId: string, flag: string): boolean {
  try {
    const raw = localStorage.getItem(AGENT_CONFIG_CACHE_KEY);
    const store: Record<string, Record<string, unknown>> = raw ? JSON.parse(raw) : {};
    return store[agentId]?.[flag] === true;
  } catch {
    return false;
  }
}

function writeFlag(agentId: string, flag: string): void {
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

/**
 * "Dismissed" memory for the welcome card. `key` is null when the welcome card is not
 * dismissable (or absent): it then never reads or writes storage.
 */
export function useWelcomeCardDismiss(agentId: string, key: string | null) {
  const [version, setVersion] = useState(0);

  // `version` re-reads storage after dismiss() without keeping a second copy of the flag.
  const dismissed = useMemo(
    () => (key ? readFlag(agentId, key) : false),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [agentId, key, version]
  );

  const dismiss = useCallback(() => {
    if (!key) return;
    writeFlag(agentId, key);
    setVersion((v) => v + 1);
  }, [agentId, key]);

  return { dismissed, dismiss };
}
