import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusPill from "./components/StatusPill";
import { ArtifactStack } from "./components/RunBrowser";
import type { Run } from "./types";

describe("StatusPill", () => {
  it("shows the effective run state", () => {
    render(<StatusPill status="unreachable" />);
    expect(screen.getByLabelText("unreachable")).toBeInTheDocument();
  });
});

describe("ArtifactStack", () => {
  it("shows selected and stacked run previews", () => {
    const run = {
      artifact_count: 4,
      thumbnail_artifact_id: "selected",
      artifact_previews: [
        { id: "selected", logical_name: "temperature.png", path: "temperature.png", kind: "image", content_type: "image/png", download_url: "/temperature.png" },
        { id: "other", logical_name: "pressure.png", path: "pressure.png", kind: "image", content_type: "image/png", download_url: "/pressure.png" },
        { id: "log", logical_name: "solver.log", path: "solver.log", kind: "log", content_type: "text/plain", download_url: null },
      ],
    } as Run;

    render(<ArtifactStack run={run} />);

    expect(screen.getByLabelText("4 artifacts")).toBeInTheDocument();
    expect(screen.getByAltText("temperature.png")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
  });
});
