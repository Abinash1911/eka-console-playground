import { describe, it, expect, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/preact";
import { useRibbonDismiss } from "@/hooks/useRibbonDismiss";

const STORE_KEY = "eka-medassist-agent-config";

describe("useRibbonDismiss", () => {
  beforeEach(() => localStorage.clear());

  it("is not dismissed by default", () => {
    const { result } = renderHook(() => useRibbonDismiss("agent-1", "ribbon_dismissed:offer"));
    expect(result.current.dismissed).toBe(false);
  });

  it("remembers a dismissal per agent and per key", () => {
    const { result } = renderHook(() => useRibbonDismiss("agent-1", "ribbon_dismissed:offer"));
    act(() => result.current.dismiss());
    expect(result.current.dismissed).toBe(true);

    expect(renderHook(() => useRibbonDismiss("agent-1", "ribbon_dismissed:offer")).result.current.dismissed).toBe(true);
    expect(renderHook(() => useRibbonDismiss("agent-2", "ribbon_dismissed:offer")).result.current.dismissed).toBe(false);
    expect(renderHook(() => useRibbonDismiss("agent-1", "ribbon_dismissed:new-offer")).result.current.dismissed).toBe(false);
  });

  it("keeps other flags in the shared store", () => {
    localStorage.setItem(STORE_KEY, JSON.stringify({ "agent-1": { feedback_hidden: true } }));
    const { result } = renderHook(() => useRibbonDismiss("agent-1", "ribbon_dismissed:offer"));
    act(() => result.current.dismiss());
    const store = JSON.parse(localStorage.getItem(STORE_KEY) as string);
    expect(store["agent-1"]).toEqual({ feedback_hidden: true, "ribbon_dismissed:offer": true });
  });

  it("does nothing without a key (fixed ribbon)", () => {
    const { result } = renderHook(() => useRibbonDismiss("agent-1", null));
    act(() => result.current.dismiss());
    expect(result.current.dismissed).toBe(false);
    expect(localStorage.getItem(STORE_KEY)).toBeNull();
  });
});
