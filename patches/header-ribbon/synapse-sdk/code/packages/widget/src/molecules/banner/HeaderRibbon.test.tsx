import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/preact";
import useMedAssistStore from "@/store/medAssistStore";
import HeaderRibbon from "./HeaderRibbon";

describe("HeaderRibbon", () => {
  beforeEach(() => {
    localStorage.clear();
    useMedAssistStore.setState({ agentId: "agent-1" });
  });

  it("fixed: stays on screen and has no close button", () => {
    render(<HeaderRibbon config={{ text: "Send 2 messages, get ₹20" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Send 2 messages, get ₹20");
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it("dismissable: hides on click and stays hidden after a remount", () => {
    const config = { text: "Send 2 messages, get ₹20", dismissable: true };
    const { unmount } = render(<HeaderRibbon config={config} />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).toBeNull();

    unmount();
    render(<HeaderRibbon config={config} />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("dismissable: a changed id shows it again", () => {
    const { unmount } = render(<HeaderRibbon config={{ text: "T", dismissable: true, id: "offer-1" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    unmount();
    render(<HeaderRibbon config={{ text: "T", dismissable: true, id: "offer-2" }} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("a fixed ribbon never writes to storage", () => {
    render(<HeaderRibbon config={{ text: "T" }} />);
    expect(localStorage.getItem("eka-medassist-agent-config")).toBeNull();
  });
});
