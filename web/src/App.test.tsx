import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusPill from "./components/StatusPill";

describe("StatusPill", () => {
  it("shows the effective run state", () => {
    render(<StatusPill status="unreachable" />);
    expect(screen.getByText("unreachable")).toBeInTheDocument();
  });
});
