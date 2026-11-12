import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/preact";
import useMedAssistStore from "@/store/medAssistStore";
import WelcomeCard from "./WelcomeCard";

describe("WelcomeCard", () => {
  beforeEach(() => {
    localStorage.clear();
    useMedAssistStore.setState({ agentId: "agent-1" });
  });

  it("fixed: stays on screen and has no dismiss link", () => {
    render(<WelcomeCard config={{ title: "Chat and earn ₹20" }} />);
    expect(screen.getByRole("heading", { name: "Chat and earn ₹20" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("dismissable: hides on click and stays hidden after a remount", () => {
    const config = { title: "Chat and earn ₹20", dismissable: true };
    const { unmount } = render(<WelcomeCard config={config} />);
    fireEvent.click(screen.getByRole("button", { name: "Maybe later" }));
    expect(screen.queryByRole("heading")).toBeNull();

    unmount();
    render(<WelcomeCard config={config} />);
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("dismissable: a changed id shows it again", () => {
    const { unmount } = render(<WelcomeCard config={{ title: "T", dismissable: true, id: "offer-1" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Maybe later" }));
    unmount();
    render(<WelcomeCard config={{ title: "T", dismissable: true, id: "offer-2" }} />);
    expect(screen.getByRole("heading", { name: "T" })).toBeInTheDocument();
  });

  it("a fixed card never writes to storage", () => {
    render(<WelcomeCard config={{ title: "T" }} />);
    expect(localStorage.getItem("eka-medassist-agent-config")).toBeNull();
  });
});
