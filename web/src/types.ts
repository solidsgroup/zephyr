export interface User {
  id: string;
  email: string;
  name: string;
  picture_url: string | null;
}

export interface GoogleAccount {
  id: string | null;
  email: string;
  name: string;
  picture_url: string | null;
  is_primary: boolean;
  linked_at: string;
}

export interface Run {
  id: string;
  owner_id: string;
  alamo_hash: string | null;
  name: string;
  status: string;
  effective_status: string;
  progress: number | null;
  last_heartbeat: string | null;
  started_at: string | null;
  ended_at: string | null;
  host: string | null;
  platform: string | null;
  scheduler_job_id: string | null;
  scheduler_system: string | null;
  scheduler_details: Record<string, string>;
  output_path: string | null;
  git_commit: string | null;
  git_repository_url: string | null;
  command: string[];
  tags: string[];
  notes: string;
  thumbnail_artifact_id: string | null;
  copy_count: number;
  artifact_count: number;
  artifact_previews: ArtifactPreview[];
  projects: RunProjectBadge[];
  created_at: string;
  updated_at: string;
}

export interface RunProjectBadge {
  id: string;
  slug: string;
  name: string;
}

export interface RunFacets {
  sites: Array<{ site: string; run_count: number }>;
}

export interface ArtifactPreview {
  id: string;
  logical_name: string;
  path: string;
  kind: string;
  content_type: string;
  download_url: string | null;
}

export interface MetadataRecord {
  raw_text: string;
  values: Record<string, string>;
  sections: Record<string, string[]>;
  digest: string;
}

export interface ThermoRow {
  sequence: number;
  values: Record<string, number | null>;
}

export interface ThermoSeries {
  segment: number;
  columns: string[];
  rows: ThermoRow[];
}

export interface RunDetail {
  run: Run;
  metadata: MetadataRecord | null;
  output: RunOutput | null;
  copies: RunCopy[];
  thermo: ThermoSeries[];
}

export interface RunCopy {
  id: string;
  run_id: string;
  site: string;
  host: string;
  path: string;
  platform: string | null;
  file_count: number;
  file_count_complete: boolean;
  data_tree_count: number;
  total_size_bytes: number | null;
  has_cell_data: boolean;
  has_node_data: boolean;
  manifest_digest: string;
  last_action: "get" | "put" | "sync";
  created_at: string;
  updated_at: string;
}

export interface RunOutput {
  stdout: string;
  stdout_truncated: boolean;
  git_diff: string;
  git_diff_truncated: boolean;
  updated_at: string;
}

export interface Artifact {
  id: string;
  sha256: string;
  size: number;
  content_type: string;
  logical_name: string;
  path: string;
  version: number;
  kind: string;
  attributes: Record<string, unknown>;
  derivation: Record<string, unknown>;
  download_url: string | null;
}

export interface Project {
  id: string;
  owner_id: string;
  slug: string;
  name: string;
  description: string;
  visibility: "private" | "group" | "public";
}

export interface ProjectDashboard extends Project {
  created_at: string;
  updated_at: string;
  last_modified_at: string;
  run_count: number;
  active_run_count: number;
  artifact_previews: ArtifactPreview[];
}

export interface ProjectFolder {
  id: string;
  project_id: string;
  parent_id: string | null;
  name: string;
  position: number;
}

export interface ProjectRunPlacement {
  run: Run;
  folder_id: string | null;
  position: number;
}

export interface ProjectLayout {
  folders: ProjectFolder[];
  runs: ProjectRunPlacement[];
}

export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  token?: string;
}
