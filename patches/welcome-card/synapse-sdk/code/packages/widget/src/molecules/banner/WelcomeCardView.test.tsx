import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/preact";
import WelcomeCardView from "./WelcomeCardView";

describe("WelcomeCardView", () => {
  it("renders title and body", () => {
    render(<WelcomeCardView title="Chat and earn ₹20" body="Send 2 messages." />);
    expect(screen.getByRole("heading", { name: "Chat and earn ₹20" })).toBeInTheDocument();
    expect(screen.getByText("Send 2 messages.")).toBeInTheDocument();
  });

  it("numbers up to three steps and ignores the rest and blanks", () => {
    render(<WelcomeCardView title="T" steps={["Say hi", " ", "Ask more", "Get ₹20", "Extra"]} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("1Say hi");
    expect(items[2]).toHaveTextContent("3Get ₹20");
    expect(screen.queryByText("Extra")).toBeNull();
  });

  it("draws no step list without steps", () => {
    render(<WelcomeCardView title="T" />);
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("has no dismiss link when fixed", () => {
    render(<WelcomeCardView title="T" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the dismiss link when dismissable and calls onDismiss", () => {
    const onDismiss = vi.fn();
    render(<WelcomeCardView title="T" dismissable onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Maybe later" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("uses a custom dismiss label", () => {
    render(<WelcomeCardView title="T" dismissable dismissLabel="Not now" />);
    expect(screen.getByRole("button", { name: "Not now" })).toBeInTheDocument();
  });
});
