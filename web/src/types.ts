export interface User {
  id: string;
  email: string;
  name: string;
  picture_url: string | null;
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
  git_commit: string | null;
  command: string[];
  tags: string[];
  notes: string;
  created_at: string;
  updated_at: string;
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
  thermo: ThermoSeries[];
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
