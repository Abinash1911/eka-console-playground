import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/preact";
import HeaderRibbonView from "./HeaderRibbonView";

describe("HeaderRibbonView", () => {
  it("renders the text", () => {
    render(<HeaderRibbonView text="Send 2 messages, get ₹20" />);
    expect(screen.getByRole("status")).toHaveTextContent("Send 2 messages, get ₹20");
  });

  it("has no close button when fixed", () => {
    render(<HeaderRibbonView text="Hello" />);
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it("shows a close button when dismissable and calls onDismiss", () => {
    const onDismiss = vi.fn();
    render(<HeaderRibbonView text="Hello" dismissable onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("uses the accent colours when no colours are given", () => {
    render(<HeaderRibbonView text="Hello" />);
    expect(screen.getByRole("status").getAttribute("style")).toBeNull();
  });

  it("applies a background and picks a readable text colour", () => {
    const { rerender } = render(<HeaderRibbonView text="Hello" background="#1e3a8a" />);
    expect(screen.getByRole("status")).toHaveStyle({ backgroundColor: "#1e3a8a", color: "#ffffff" });
    rerender(<HeaderRibbonView text="Hello" background="#fef3c7" />);
    expect(screen.getByRole("status")).toHaveStyle({ color: "#000000" });
    rerender(<HeaderRibbonView text="Hello" background="#fff" />);
    expect(screen.getByRole("status")).toHaveStyle({ color: "#000000" });
  });

  it("an explicit text colour wins over the automatic one", () => {
    render(<HeaderRibbonView text="Hello" background="#1e3a8a" textColor="#ffd54a" />);
    expect(screen.getByRole("status")).toHaveStyle({ color: "#ffd54a" });
  });

  it("ignores values that are not hex colours", () => {
    render(<HeaderRibbonView text="Hello" background="red; display:none" textColor="url(x)" />);
    expect(screen.getByRole("status").getAttribute("style")).toBeNull();
  });
});
