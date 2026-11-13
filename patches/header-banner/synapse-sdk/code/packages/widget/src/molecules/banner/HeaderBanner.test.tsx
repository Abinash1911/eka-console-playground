import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/preact";
import HeaderBanner from "./HeaderBanner";

describe("HeaderBanner", () => {
  it("renders the text", () => {
    render(<HeaderBanner text="Chat and earn coins" />);
    expect(screen.getByRole("status")).toHaveTextContent("Chat and earn coins");
  });

  it("takes its colours from the accent colour, not from inline styles", () => {
    render(<HeaderBanner text="Chat and earn coins" />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveClass("bg-primary", "text-primary-foreground");
    expect(banner.getAttribute("style")).toBeNull();
  });

  it("has no buttons (always shown)", () => {
    render(<HeaderBanner text="Chat and earn coins" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
