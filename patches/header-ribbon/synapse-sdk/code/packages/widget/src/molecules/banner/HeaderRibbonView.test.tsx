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
});
