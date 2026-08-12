import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatusPill from "./components/StatusPill";
import RunBrowser, { ArtifactStack } from "./components/RunBrowser";
import JobsPage from "./pages/JobsPage";
import { ArtifactViewer, CopyLocations, SlurmDetails } from "./pages/RunPage";
import type { Artifact, Run, RunCopy } from "./types";

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
        { id: "movie", logical_name: "movie.webm", path: "movie.webm", kind: "file", content_type: "video/webm", download_url: "/movie.webm" },
      ],
    } as Run;

    render(<ArtifactStack run={run} />);

    expect(screen.getByLabelText("4 artifacts")).toBeInTheDocument();
    expect(screen.getByAltText("temperature.png")).toBeInTheDocument();
    expect(screen.getByLabelText("movie.webm")).toHaveAttribute("src", "/movie.webm");
    expect(screen.getByText("+1")).toBeInTheDocument();
  });
});

describe("ArtifactViewer", () => {
  it("opens WebM media fullscreen and closes with Escape", () => {
    const close = vi.fn();
    const artifact = {
      id: "movie",
      sha256: "a".repeat(64),
      size: 100,
      content_type: "video/webm",
      logical_name: "movie.webm",
      path: "movies/movie.webm",
      version: 1,
      kind: "file",
      attributes: {},
      derivation: {},
      download_url: "/movie.webm",
    } as Artifact;
    const view = render(<ArtifactViewer artifact={artifact} url="/movie.webm" onClose={close} />);
    expect(within(view.container).getByRole("dialog", { name: "Preview movie.webm" })).toBeInTheDocument();
    expect(within(view.container).getByLabelText("movie.webm")).toHaveAttribute("controls");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
  });
});

describe("RunBrowser", () => {
  it("uses Ctrl-click for multi-selection without checkboxes", async () => {
    const runs = [run("one", "Run one"), run("two", "Run two")];
    vi.stubGlobal("fetch", vi.fn((request: RequestInfo | URL) => Promise.resolve(new Response(JSON.stringify(
      String(request).includes("/runs/facets")
        ? { sites: [{ site: "stampede3", run_count: 2 }] }
        : String(request).includes("/projects?")
          ? [{ id: "project", owner_id: "owner", slug: "study", name: "Study", description: "", visibility: "private" }]
          : String(request).includes("/runs/batch")
            ? { added: 2, already_present: 0 }
        : runs,
    ), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const view = render(
      <QueryClientProvider client={queryClient}>
        <RunBrowser open onClose={() => undefined} />
      </QueryClientProvider>,
    );

    const browser = within(view.container);
    const first = await browser.findByRole("link", { name: "Run one" });
    const second = browser.getByRole("link", { name: "Run two" });
    expect(browser.queryByRole("checkbox")).not.toBeInTheDocument();

    fireEvent.click(first, { ctrlKey: true });
    expect(browser.getByText("Ctrl/Cmd-click another run to compare")).toBeInTheDocument();
    fireEvent.click(second, { ctrlKey: true });
    expect(browser.getByRole("button", { name: "Compare 2" })).toBeInTheDocument();
    fireEvent.click(browser.getByRole("button", { name: "Add to project" }));
    const project = await browser.findByRole("option", { name: "Study" });
    fireEvent.change(project.closest("select")!, { target: { value: "project" } });
    fireEvent.click(browser.getByRole("button", { name: "Add runs" }));
    expect(await browser.findByText("Added 2 to Study")).toBeInTheDocument();
    expect(first.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
    expect(second.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
  });

  it("sends path search and storage filters to the server", async () => {
    const fetchMock = vi.fn((request: RequestInfo | URL) => Promise.resolve(new Response(JSON.stringify(
      String(request).includes("/runs/facets")
        ? { sites: [{ site: "stampede3", run_count: 4 }] }
        : [run("one", "Run one")],
    ), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const view = render(
      <QueryClientProvider client={queryClient}>
        <RunBrowser open onClose={() => undefined} />
      </QueryClientProvider>,
    );

    const browser = within(view.container);
    await browser.findByRole("option", { name: "stampede3 (4)" });
    fireEvent.change(browser.getByLabelText("Search runs"), { target: { value: ".gif" } });
    fireEvent.change(browser.getByLabelText("Filter storage site"), { target: { value: "stampede3" } });
    fireEvent.change(browser.getByLabelText("Filter thumbnail"), { target: { value: "true" } });

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([request]) => String(request));
      expect(requestedUrls.some((url) =>
        url.includes("search=.gif")
        && url.includes("site=stampede3")
        && url.includes("has_thumbnail=true"),
      )).toBe(true);
    });
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

describe("CopyLocations", () => {
  it("shows file counts, storage paths, and simulation data markers", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const copy = {
      id: "copy-one",
      run_id: "run-one",
      site: "stampede3",
      host: "login1",
      path: "/scratch/brunnels/output.481516",
      platform: "Linux",
      file_count: 12,
      file_count_complete: false,
      data_tree_count: 1248,
      total_size_bytes: null,
      has_cell_data: true,
      has_node_data: true,
      manifest_digest: "a".repeat(64),
      last_action: "sync",
      created_at: "2026-08-12T12:00:00Z",
      updated_at: "2026-08-12T13:00:00Z",
    } satisfies RunCopy;

    render(<CopyLocations copies={[copy]} />);
    const panel = screen.getByRole("heading", { name: "Copies" }).closest("section")!;
    const locations = within(panel);

    expect(locations.getByText("1 known location")).toBeInTheDocument();
    expect(locations.getByText("12 indexed files")).toBeInTheDocument();
    expect(locations.getByText("1,248 BoxLib trees · Shallow inventory")).toBeInTheDocument();
    expect(locations.getByText("Simulation data")).toBeInTheDocument();
    expect(locations.getByText("cell")).toBeInTheDocument();
    expect(locations.getByText("node")).toBeInTheDocument();
    fireEvent.click(locations.getByRole("button", { name: "Copy path" }));
    expect(writeText).toHaveBeenCalledWith("/scratch/brunnels/output.481516");
  });
});
