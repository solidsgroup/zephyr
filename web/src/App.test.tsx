import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatusPill from "./components/StatusPill";
import RunBrowser, { ArtifactStack } from "./components/RunBrowser";
import MetadataTable from "./components/MetadataTable";
import { compactPathValues } from "./comparisonPaths";
import PathTail from "./components/PathTail";
import JobsPage from "./pages/JobsPage";
import ProjectsPage from "./pages/ProjectsPage";
import SettingsPage from "./pages/SettingsPage";
import { ArtifactViewer, CopyLocations, SlurmDetails } from "./pages/RunPage";
import type { Artifact, Run, RunCopy } from "./types";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

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
    copy_count: 0,
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

describe("MetadataTable", () => {
  it("contracts common path segments and preserves full values on hover", () => {
    const first = "/scratch/projects/alamo/case-one/results/output.101";
    const second = "/scratch/projects/alamo/case-two/results/output.101";
    expect(compactPathValues("Execution · Output path", [first, second])).toEqual([
      "…/case-one/…",
      "…/case-two/…",
    ]);
    expect(compactPathValues("Input", ["cases/one/input.in", "cases/two/input.in"])).toEqual([
      "…/one/…",
      "…/two/…",
    ]);

    render(<MetadataTable records={[
      { name: "First", values: { "Execution · Output path": first } },
      { name: "Second", values: { "Execution · Output path": second } },
    ]} />);

    expect(screen.getByText("…/case-one/…")).toBeInTheDocument();
    expect(screen.getByText("…/case-two/…")).toBeInTheDocument();
    expect(screen.getByTitle(first)).toHaveTextContent("…/case-one/…");
    expect(screen.getByTitle(second)).toHaveTextContent("…/case-two/…");
  });

  it("wraps non-path values without changing their content", () => {
    const value = "a very long value that should wrap rather than widen the comparison column";
    render(<MetadataTable records={[{ name: "Run", values: { Notes: value } }]} />);
    expect(screen.getByTitle(value).querySelector(".comparison-cell-value")).toHaveTextContent(value);
  });
});

describe("SettingsPage", () => {
  it("shows the required primary account and lets users unlink an alternate", async () => {
    window.history.replaceState(null, "", "/settings?google_link=linked");
    const accounts = [
      { id: null, email: "owner@solids.group", name: "Owner", picture_url: null, is_primary: true, linked_at: "2026-08-01T12:00:00Z" },
      { id: "linked-account", email: "owner@gmail.com", name: "Owner", picture_url: null, is_primary: false, linked_at: "2026-08-20T12:00:00Z" },
    ];
    const fetchMock = vi.fn((request: RequestInfo | URL, options?: RequestInit) => {
      const url = String(request);
      if (options?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
      const body = url.endsWith("/auth/google-accounts") ? accounts : [];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={queryClient}><SettingsPage /></QueryClientProvider>);

    expect(await screen.findByText("owner@solids.group")).toBeInTheDocument();
    expect(screen.getByText("owner@gmail.com")).toBeInTheDocument();
    expect(screen.getByText("Primary · required @solids.group account")).toBeInTheDocument();
    expect(screen.getByText("Google account linked. You can now use it to sign in.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link Google account" })).toHaveAttribute("href", "/api/v1/auth/google-accounts/link");
    expect(screen.getAllByRole("button", { name: "Unlink" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/google-accounts/linked-account",
      expect.objectContaining({ method: "DELETE" }),
    ));
  });
});

describe("ArtifactStack", () => {
  it("shows selected and stacked run previews without autoplaying every video", async () => {
    const run = {
      artifact_count: 4,
      thumbnail_artifact_id: "movie",
      artifact_previews: [
        { id: "selected", logical_name: "temperature.png", path: "temperature.png", kind: "image", content_type: "image/png", download_url: "/temperature.png" },
        { id: "other", logical_name: "pressure.png", path: "pressure.png", kind: "image", content_type: "image/png", download_url: "/pressure.png" },
        { id: "movie", logical_name: "movie.webm", path: "movie.webm", kind: "file", content_type: "video/webm", download_url: "/movie.webm" },
      ],
    } as Run;

    render(<ArtifactStack run={run} />);

    expect(screen.getByLabelText("4 artifacts")).toBeInTheDocument();
    expect(screen.getByAltText("temperature.png")).toBeInTheDocument();
    const movie = await screen.findByLabelText("movie.webm");
    expect(movie).toHaveAttribute("src", "/movie.webm");
    expect(movie).not.toHaveAttribute("autoplay");
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

describe("PathTail", () => {
  it("measures the available width and removes the beginning of long paths", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 100 } as DOMRect);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      font: "",
      measureText: (text: string) => ({ width: text.length * 10 }),
    } as CanvasRenderingContext2D);
    const path = "/scratch/brunnels/alamo-runs/results/output.481516";

    render(<PathTail value={path} />);

    const rendered = screen.getByLabelText(path).textContent ?? "";
    expect(rendered.startsWith("…")).toBe(true);
    expect(rendered.endsWith(".481516")).toBe(true);
    expect(rendered).not.toContain("/scratch");
  });
});

describe("RunBrowser", () => {
  it("uses Ctrl-click and Shift-click for multi-selection without navigating", async () => {
    const runs = [run("one", "Run one"), run("two", "Run two"), run("three", "Run three")];
    const fetchMock = vi.fn((request: RequestInfo | URL, options?: RequestInit) => {
      void options;
      return Promise.resolve(new Response(JSON.stringify(
        String(request).includes("/runs/facets")
          ? { sites: [{ site: "stampede3", run_count: 2 }] }
          : String(request).includes("/projects/project/layout")
            ? { folders: [{ id: "cases", project_id: "project", parent_id: null, name: "Cases", position: 0 }, { id: "gpu", project_id: "project", parent_id: "cases", name: "GPU", position: 0 }], runs: [] }
          : String(request).includes("/projects?")
            ? [{ id: "project", owner_id: "owner", slug: "study", name: "Study", description: "", visibility: "private" }]
            : String(request).includes("/runs/batch")
              ? { added: 3, already_present: 0 }
              : runs,
      ), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const close = vi.fn();
    const view = render(
      <QueryClientProvider client={queryClient}>
        <RunBrowser open onClose={close} />
      </QueryClientProvider>,
    );

    const browser = within(view.container);
    const first = await browser.findByRole("link", { name: "Run one" });
    const second = browser.getByRole("link", { name: "Run two" });
    const third = browser.getByRole("link", { name: "Run three" });
    expect(browser.queryByRole("checkbox")).not.toBeInTheDocument();

    fireEvent.click(first, { ctrlKey: true });
    expect(browser.getByRole("button", { name: "Add to project" })).toBeInTheDocument();
    expect(browser.queryByRole("button", { name: /Compare/ })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Shift" });
    fireEvent.mouseEnter(third.closest(".run-browser-item")!);
    expect(first.closest(".run-browser-item")).toHaveAttribute("data-range-preview", "true");
    expect(second.closest(".run-browser-item")).toHaveAttribute("data-range-preview", "true");
    expect(third.closest(".run-browser-item")).toHaveAttribute("data-range-preview", "true");
    fireEvent.keyUp(window, { key: "Shift" });
    expect(second.closest(".run-browser-item")).not.toHaveAttribute("data-range-preview");
    fireEvent.click(third, { shiftKey: true });
    expect(browser.getByRole("button", { name: "Compare 3" })).toBeInTheDocument();
    await waitFor(() => expect(`${window.location.pathname}${window.location.search}`).toBe("/runs/compare?ids=one,two,three"));
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(browser.getByRole("button", { name: "Add to project" }));
    const project = await browser.findByRole("option", { name: "Study" });
    fireEvent.change(project.closest("select")!, { target: { value: "project" } });
    const gpuFolder = await browser.findByRole("option", { name: /GPU/ });
    fireEvent.change(gpuFolder.closest("select")!, { target: { value: "gpu" } });
    fireEvent.click(browser.getByRole("button", { name: "Add 3 runs" }));
    expect(await browser.findByText("Added 3 to Study")).toBeInTheDocument();
    const addCall = fetchMock.mock.calls.find(([request]) => String(request).includes("/runs/batch"));
    expect(JSON.parse(String(addCall?.[1]?.body))).toEqual({ run_ids: ["one", "two", "three"], folder_id: "gpu" });
    expect(first.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
    expect(second.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
    expect(third.closest(".run-browser-item")).toHaveAttribute("data-selected", "true");
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
    fireEvent.change(browser.getByLabelText("Filter copies"), { target: { value: "false" } });
    fireEvent.change(browser.getByLabelText("Filter artifacts"), { target: { value: "true" } });
    fireEvent.change(browser.getByLabelText("Sort runs"), { target: { value: "artifacts_desc" } });
    fireEvent.click(browser.getByRole("button", { name: /Uncategorized only/ }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([request]) => String(request));
      expect(requestedUrls.some((url) =>
        url.includes("search=.gif")
        && url.includes("site=stampede3")
        && url.includes("has_thumbnail=true")
        && url.includes("has_copies=false")
        && url.includes("has_artifacts=true")
        && url.includes("sort=artifacts_desc")
        && url.includes("uncategorized=true"),
      )).toBe(true);
    });
  });

  it("creates projects and destination folders while adding a run", async () => {
    const ownedRun = run("one", "Run one");
    const editableProjects: Array<Record<string, unknown>> = [];
    const createdProject = { id: "created", owner_id: "owner", slug: "parameter-study", name: "Parameter study", description: "", visibility: "private" };
    const createdFolder = { id: "cases", project_id: "created", parent_id: null, name: "Cases", position: 0 };
    const folders: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn((request: RequestInfo | URL, options?: RequestInit) => {
      const url = String(request);
      let body: unknown = [ownedRun];
      let status = 200;
      if (url.includes("/runs/facets")) {
        body = { sites: [] };
      } else if (url.includes("/projects?editable=true")) {
        body = editableProjects;
      } else if (url.endsWith("/projects") && options?.method === "POST") {
        editableProjects.push(createdProject);
        body = createdProject;
        status = 201;
      } else if (url.includes("/projects/created/layout")) {
        body = { folders, runs: [] };
      } else if (url.endsWith("/projects/created/folders") && options?.method === "POST") {
        folders.push(createdFolder);
        body = createdFolder;
        status = 201;
      } else if (url.endsWith("/projects/created/runs/batch")) {
        body = { added: 1, already_present: 0 };
      }
      return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={queryClient}><RunBrowser open onClose={() => undefined} /></QueryClientProvider>);
    const browser = within(view.container);

    fireEvent.click(await browser.findByRole("link", { name: "Run one" }), { ctrlKey: true });
    fireEvent.click(browser.getByRole("button", { name: "Add to project" }));
    fireEvent.click(await browser.findByRole("button", { name: "＋ New project" }));
    fireEvent.change(browser.getByLabelText("New project name"), { target: { value: "Parameter study" } });
    expect(browser.getByLabelText("New project slug")).toHaveValue("parameter-study");
    fireEvent.click(browser.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(browser.getByLabelText("Choose project")).toHaveValue("created"));

    const newFolderButton = browser.getByRole("button", { name: "＋ New folder" });
    await waitFor(() => expect(newFolderButton).toBeEnabled());
    fireEvent.click(newFolderButton);
    fireEvent.change(browser.getByLabelText("New folder name"), { target: { value: "Cases" } });
    fireEvent.click(browser.getByRole("button", { name: "Create folder" }));
    await waitFor(() => expect(browser.getByLabelText("Choose project folder")).toHaveValue("cases"));
    fireEvent.click(browser.getByRole("button", { name: "Add run" }));

    await waitFor(() => {
      const projectCall = fetchMock.mock.calls.find(([request, options]) => String(request).endsWith("/projects") && options?.method === "POST");
      expect(JSON.parse(String(projectCall?.[1]?.body))).toEqual({ name: "Parameter study", slug: "parameter-study", visibility: "private" });
      const folderCall = fetchMock.mock.calls.find(([request]) => String(request).endsWith("/projects/created/folders"));
      expect(JSON.parse(String(folderCall?.[1]?.body))).toEqual({ name: "Cases", parent_id: null });
      const addCall = fetchMock.mock.calls.find(([request]) => String(request).endsWith("/projects/created/runs/batch"));
      expect(JSON.parse(String(addCall?.[1]?.body))).toEqual({ run_ids: ["one"], folder_id: "cases" });
    });
  });
});

describe("ProjectsPage", () => {
  it("shows the full record, selects ranges, and moves a run by drag and drop", async () => {
    const project = { id: "project", owner_id: "owner", slug: "study", name: "Study", description: "Project data", visibility: "private" };
    const otherProject = { id: "other-project", owner_id: "owner", slug: "other-study", name: "Other study", description: "More data", visibility: "private" };
    const projectRun = { ...run("simulation", "Simulation one"), copy_count: 2, artifact_count: 1, output_path: "/scratch/alamo-runs/results/output.one", scheduler_system: "slurm", scheduler_job_id: "101", scheduler_details: { partition: "gpu", job_name: "simulation-one" } };
    const secondRun = { ...run("simulation-two", "Simulation two"), copy_count: 0, artifact_count: 3, output_path: "/scratch/alamo-runs/results/output.two", scheduler_system: "slurm", scheduler_job_id: "102", scheduler_details: { partition: "gpu", job_name: "simulation-two" } };
    const thirdRun = { ...run("simulation-three", "Simulation three"), copy_count: 1, artifact_count: 0, output_path: "/scratch/alamo-runs/results/output.three", scheduler_system: "slurm", scheduler_job_id: "103", scheduler_details: { partition: "gpu", job_name: "simulation-three" } };
    const otherRun = { ...run("other-simulation", "Other simulation"), output_path: "/scratch/alamo-runs/results/output.other" };
    const projectRuns = [projectRun, secondRun, thirdRun, otherRun];
    const layout = {
      folders: [
        { id: "cases", project_id: "project", parent_id: null, name: "Cases", position: 0 },
        { id: "gpu", project_id: "project", parent_id: "cases", name: "GPU", position: 0 },
      ],
      runs: projectRuns.slice(0, 3).map((item, position) => ({ run: item, folder_id: null, position })),
    };
    const fetchMock = vi.fn((request: RequestInfo | URL, options?: RequestInit) => {
      const url = String(request);
      let body: unknown = [];
      if (url.includes("/comparisons/runs")) {
        body = { runs: projectRuns.slice(0, 3).map((item) => ({ run: item, metadata: { CASE: item.name, DIM: "3" }, thermo: [] })) };
      } else if (url.includes("/auth/me")) {
        body = { user: { id: "owner", email: "owner@solids.group", name: "Owner", picture_url: null }, csrf_token: "csrf" };
      } else if (url.includes("/projects/project/runs/placement/batch")) {
        const request = JSON.parse(String(options?.body));
        body = request.run_ids.map((id: string, position: number) => ({ run: projectRuns.find((item) => item.id === id), folder_id: "gpu", position }));
      } else if (url.includes("/projects/other-project/layout")) {
        body = { folders: [], runs: [{ run: otherRun, folder_id: null, position: 0 }] };
      } else if (url.includes("/projects/project/layout")) {
        body = layout;
      } else if (url.includes("/projects")) {
        body = [project, otherProject];
      } else if (url.includes("/runs?") && url.includes("search=")) {
        body = [secondRun];
      } else if (url.includes("/runs/") && url.endsWith("/artifacts")) {
        body = [];
      } else if (url.includes("/runs/")) {
        const id = url.split("/runs/")[1].split("?")[0];
        body = { run: projectRuns.find((item) => item.id === id), metadata: null, output: null, copies: [], thermo: [] };
      }
      return Promise.resolve(new Response(JSON.stringify(body), { status: options?.method === "DELETE" ? 204 : 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/projects/study/runs/simulation-two");
    window.localStorage.setItem("zephyr:collapsed-project-folders:project", JSON.stringify(["cases"]));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(["me"], { id: "owner", email: "owner@solids.group", name: "Owner", picture_url: null });

    const view = render(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);
    const page = within(view.container);
    expect(await page.findByRole("combobox", { name: "Select project" })).toHaveValue("project");
    expect(await page.findByRole("button", { name: "stdout" })).toBeInTheDocument();
    expect(page.getByRole("button", { name: "git diff" })).toBeInTheDocument();
    expect(view.container.querySelector(".project-run-row[data-active='true']")).toHaveTextContent("Simulation two");
    const casesButton = (await page.findByText("Cases")).closest("button")!;
    expect(page.queryByText("GPU")).not.toBeInTheDocument();
    fireEvent.click(casesButton);
    expect(page.getByText("GPU")).toBeInTheDocument();
    await waitFor(() => expect(window.localStorage.getItem("zephyr:collapsed-project-folders:project")).toBe("[]"));

    const runRows = Array.from(view.container.querySelectorAll<HTMLButtonElement>(".project-run-row"));
    fireEvent.click(runRows[0]);
    expect(window.location.pathname).toBe("/projects/study/runs/simulation");
    fireEvent.keyDown(window, { key: "Shift" });
    fireEvent.mouseEnter(runRows[2]);
    expect(runRows.every((row) => row.dataset.rangePreview === "true")).toBe(true);
    fireEvent.keyUp(window, { key: "Shift" });
    fireEvent.click(runRows[2], { shiftKey: true });
    expect(window.location.pathname).toBe("/projects/study/runs/simulation-three");
    expect(runRows).toHaveLength(3);
    expect(runRows.every((row) => row.dataset.selected === "true")).toBe(true);
    expect(await page.findByRole("heading", { name: "Compare 3 runs" })).toBeInTheDocument();
    const thermoSection = (await page.findByRole("heading", { name: "Thermodynamics" })).closest("details");
    expect(thermoSection).not.toHaveAttribute("open");
    expect(page.getByRole("heading", { name: "Run provenance" }).closest("details")).toHaveAttribute("open");
    const metadataSection = (await page.findByRole("heading", { name: "Metadata comparison" })).closest("details")!;
    expect(metadataSection).toHaveAttribute("open");
    expect(page.getByText("SLURM · Partition")).toBeInTheDocument();
    expect(page.getByText("DIM")).toBeInTheDocument();
    fireEvent.click(page.getByRole("checkbox", { name: "Hide similar" }));
    expect(page.queryByText("SLURM · Partition")).not.toBeInTheDocument();
    expect(page.queryByText("DIM")).not.toBeInTheDocument();
    expect(page.getByText("SLURM · Job Name")).toBeInTheDocument();
    fireEvent.click(metadataSection.querySelector("summary")!);
    await waitFor(() => expect(metadataSection).not.toHaveAttribute("open"));
    expect(page.getByRole("link", { name: "Compare" })).toHaveAttribute("href", "/compare?ids=simulation,simulation-two,simulation-three");

    const runButton = runRows[0];
    const gpuDropTarget = page.getByText("GPU").closest(".project-folder-row")!;
    const transfer = { effectAllowed: "none", dropEffect: "none", setData: vi.fn(), getData: vi.fn(() => "simulation") };
    fireEvent.dragStart(runButton, { dataTransfer: transfer });
    fireEvent.dragOver(gpuDropTarget, { dataTransfer: transfer });
    fireEvent.drop(gpuDropTarget, { dataTransfer: transfer });

    await waitFor(() => {
      const placementCall = fetchMock.mock.calls.find(([request]) => String(request).includes("/placement/batch"));
      expect(placementCall).toBeDefined();
      expect(JSON.parse(String(placementCall?.[1]?.body))).toEqual({ run_ids: ["simulation", "simulation-two", "simulation-three"], folder_id: "gpu", position: 0 });
    });

    fireEvent.change(page.getByLabelText("Search project runs"), { target: { value: "Simulation two" } });
    await waitFor(() => expect(view.container.querySelectorAll(".project-run-row")).toHaveLength(1));
    expect(page.getByText("1 of 3 runs")).toBeInTheDocument();
    expect(page.getByText("Cases")).toBeInTheDocument();
    expect(page.getByText("GPU")).toBeInTheDocument();

    fireEvent.change(page.getByLabelText("Search project runs"), { target: { value: "" } });
    await waitFor(() => expect(view.container.querySelectorAll(".project-run-row")).toHaveLength(3));
    fireEvent.change(page.getByLabelText("Sort project runs"), { target: { value: "copies_desc" } });
    expect(Array.from(view.container.querySelectorAll(".project-run-row strong")).map((node) => node.textContent)).toEqual(["Simulation one", "Simulation three", "Simulation two"]);
    fireEvent.change(page.getByLabelText("Filter project copies"), { target: { value: "false" } });
    expect(view.container.querySelectorAll(".project-run-row")).toHaveLength(1);
    expect(page.getByText("1 of 3 runs")).toBeInTheDocument();

    fireEvent.change(page.getByLabelText("Select project"), { target: { value: "other-project" } });
    await waitFor(() => expect(window.location.pathname).toBe("/projects/other-study/runs/other-simulation"));
    expect(await page.findByText("Other simulation")).toBeInTheDocument();
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
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-12T15:00:00Z"));
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

    const view = render(<CopyLocations copies={[copy]} />);
    const panel = within(view.container).getByRole("heading", { name: "Copies" }).closest("section")!;
    const locations = within(panel);

    expect(locations.getByText("1 known location")).toBeInTheDocument();
    expect(locations.getByText("12 files")).toBeInTheDocument();
    expect(locations.getByText("Data")).toBeInTheDocument();
    expect(locations.getByText("2 hr")).toBeInTheDocument();
    expect(locations.queryByText(/BoxLib trees|Shallow inventory|Simulation data|cell|node/i)).not.toBeInTheDocument();
    fireEvent.click(locations.getByRole("button", { name: "Copy path" }));
    expect(writeText).toHaveBeenCalledWith("/scratch/brunnels/output.481516");
  });
});
