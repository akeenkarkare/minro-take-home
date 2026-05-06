/**
 * Server-side API client.
 *
 * Used in Server Components and route handlers. The API base URL on the
 * server is the docker-compose service name, not the public NEXT_PUBLIC_ one,
 * so we can reach it without exposing the API to the browser directly.
 */
const SERVER_API_BASE = process.env.API_URL ?? "http://api:8000";

export type PersonOut = {
  email: string;
  name: string;
  title: string | null;
  company: string | null;
  location: string | null;
  bio: string | null;
  linkedin_url: string | null;
  twitter_url: string | null;
  github_url: string | null;
  avatar_url: string | null;
  company_domain: string | null;
  company_description: string | null;
  company_logo_url: string | null;
  sources: string[];
  confidence: number;
  field_confidence: Record<string, number>;
  enriched_at: string;
};

export type PeopleListItem = {
  email: string;
  name: string;
  title: string | null;
  company: string | null;
  location: string | null;
  avatar_url: string | null;
  confidence: number;
  sources: string[];
  enriched_at: string;
};

export type JobOut = {
  id: string;
  kind: "single" | "batch";
  status: "pending" | "running" | "complete" | "failed";
  total: number;
  done: number;
  failed_count: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${SERVER_API_BASE}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API ${path} -> ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export async function listPeople(params: {
  min_confidence?: number;
  company?: string;
  location?: string;
  has_linkedin?: boolean;
  sort_by?: "confidence" | "name" | "enriched_at";
  limit?: number;
  offset?: number;
}): Promise<{ total: number; items: PeopleListItem[] }> {
  const q = new URLSearchParams();
  if (params.min_confidence !== undefined)
    q.set("min_confidence", String(params.min_confidence));
  if (params.company) q.set("company", params.company);
  if (params.location) q.set("location", params.location);
  if (params.has_linkedin !== undefined)
    q.set("has_linkedin", String(params.has_linkedin));
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset) q.set("offset", String(params.offset));
  return getJSON(`/people?${q.toString()}`);
}

export async function getPerson(email: string): Promise<PersonOut> {
  return getJSON(`/people/${encodeURIComponent(email)}`);
}

export async function getJob(id: string): Promise<JobOut> {
  return getJSON(`/jobs/${id}`);
}

export async function getHealth(): Promise<unknown> {
  return getJSON(`/health`);
}

export function serverApiBase(): string {
  return SERVER_API_BASE;
}
