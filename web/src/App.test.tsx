import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatusPill from "./components/StatusPill";
import RunBrowser, { ArtifactStack } from "./components/RunBrowser";
import JobsPage from "./pages/JobsPage";
import { SlurmDetails } from "./pages/RunPage";
import type { Run } from "./types";

afterEach(() => vi.unstubAllGlobals());

function run(id: string, name: string): Run {
  return {
    id,
    owner_id: "owner",
    alamo_hash: `hash-${id}`,
    name,
    status: "completed",
    effective_status: "completed",
    progress: 100,
    last_heartbeat: "2026-08-03T20:00:00Z",
    started_at: null,
    ended_at: null,
    host: "cluster",
    platform: null,
    scheduler_job_id: null,
    scheduler_system: null,
    scheduler_details: {},
    output_path: null,
    git_commit: null,
    git_repository_url: null,
    command: [],
    tags: [],
    notes: "",
    thumbnail_artifact_id: null,
    artifact_count: 0,
    artifact_previews: [],
    created_at: "2026-08-03T20:00:00Z",
    updated_at: "2026-08-03T20:00:00Z",
  };
}

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

describe("RunBrowser", () => {
  it("uses Ctrl-click for multi-selection without checkboxes", async () => {
    const runs = [run("one", "Run one"), run("two", "Run two")];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(runs), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <RunBrowser open onClose={() => undefined} />
      </QueryClientProvider>,
    );

    const first = await screen.findByRole("link", { name: "Run one" });
    const second = screen.getByRole("link", { name: "Run two" });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    fireEvent.click(first, { ctrlKey: true });
    expect(screen.getByText("Ctrl/Cmd-click another run to compare")).toBeInTheDocument();
    fireEvent.click(second, { ctrlKey: true });
    expect(screen.getByRole("button", { name: "Compare 2 runs" })).toBeInTheDocument();
    expect(first.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
    expect(second.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
  });
});

describe("JobsPage", () => {
  it("shows SLURM context and marks newly arriving jobs for animation", async () => {
    const first = {
      ...run("one", "Ignition sweep"),
      scheduler_job_id: "481516",
      scheduler_system: "slurm",
      scheduler_details: {
        cluster: "stampede3",
        job_name: "alamo-ignition",
        partition: "gpu-a100",
        node_list: "compute-041",
        node_count: "1",
        task_count: "16",
        cpus_per_task: "16",
        job_gpu_ids: "0,1",
        gpus_on_node: "a100:2",
        submit_directory: "/work/alamo",
        plot_file: "output.481516",
      },
      output_path: null,
      effective_status: "running",
      status: "running",
    };
    const second = {
      ...first,
      id: "two",
      name: "Packing study",
      scheduler_job_id: "481517",
      scheduler_details: {
        ...first.scheduler_details,
        cluster: "lonestar6",
        job_name: "alamo-packing",
        plot_file: "output.481517",
      },
      output_path: "/work/alamo/output.481517",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      run: first,
      metadata: null,
      output: {
        stdout: "Advancing timestep 42\n",
        stdout_truncated: false,
        git_diff: "",
        git_diff_truncated: false,
        updated_at: "2026-08-03T20:01:00Z",
      },
      thermo: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    queryClient.setQueryData(["runs", "slurm-jobs"], [first]);

    render(
      <QueryClientProvider client={queryClient}>
        <JobsPage />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("heading", { name: "On stampede3 now" })).toBeInTheDocument();
    expect(screen.getByText("alamo-ignition")).toBeInTheDocument();
    expect(screen.getByText("481516")).toBeInTheDocument();
    expect(screen.getByText("gpu-a100")).toBeInTheDocument();
    expect(screen.getByText("compute-041")).toBeInTheDocument();
    expect(screen.getByLabelText("1 node")).toBeInTheDocument();
    expect(screen.getByLabelText("16 tasks")).toBeInTheDocument();
    expect(screen.getByLabelText("2 GPUs")).toBeInTheDocument();
    expect(screen.getByText("/work/alamo/output.481516")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show stdout for alamo-ignition" }));
    expect(await screen.findByText("Advancing timestep 42")).toBeInTheDocument();

    act(() => queryClient.setQueryData(["runs", "slurm-jobs"], [second, first]));
    expect(await screen.findByRole("heading", { name: "On lonestar6 now" })).toBeInTheDocument();
    const arrival = await screen.findByRole("link", { name: /Packing study/ });
    expect(arrival.closest(".job-record")).toHaveAttribute("data-new", "true");
  });
});

describe("SlurmDetails", () => {
  it("shows processed scheduler context and copies the output directory", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const slurmRun = {
      ...run("slurm", "output.11930715"),
      scheduler_system: "slurm",
      scheduler_job_id: "SLURM_JOB_ID=11930715",
      scheduler_details: {
        job_name: "lm3d-30mw-full-normal",
        cluster: "nova",
        partition: "nova",
        node_count: "1",
        task_count: "4",
        job_gpu_ids: "0,1,2,3",
        memory_per_node: "409600",
        submit_directory: "/work/brunnels/alamo",
        plot_file: "output.11930715",
      },
    };

    render(<SlurmDetails run={slurmRun} />);
    const panel = screen.getByRole("heading", { name: "SLURM" }).closest("section")!;
    const table = within(panel);

    expect(table.getByText("lm3d-30mw-full-normal")).toBeInTheDocument();
    expect(table.getByText("11930715")).toBeInTheDocument();
    expect(table.getByText("GPUs").closest("tr")).toHaveTextContent("4");
    expect(table.getByText("Memory per node").closest("tr")).toHaveTextContent("400 GiB");
    expect(table.getByText("/work/brunnels/alamo/output.11930715")).toBeInTheDocument();
    fireEvent.click(table.getByRole("button", { name: "Copy output directory" }));
    expect(writeText).toHaveBeenCalledWith("/work/brunnels/alamo/output.11930715");
  });
});
