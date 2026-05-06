"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";
import Link from "next/link";

type Job = {
  id: string;
  kind: string;
  status: "pending" | "running" | "complete" | "failed";
  total: number;
  done: number;
  failed_count: number;
  error: string | null;
};

export default function UploadPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll the job until it finishes.
  useEffect(() => {
    if (!job || job.status === "complete" || job.status === "failed") return;
    const t = setInterval(async () => {
      try {
        const r = await fetch(`/api/proxy/jobs/${job.id}`);
        if (!r.ok) return;
        const next = (await r.json()) as Job;
        setJob(next);
      } catch {
        // ignore transient errors
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job]);

  async function submit() {
    if (!file) return;
    setError(null);
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("/api/proxy/enrich/batch", { method: "POST", body: fd });
      if (!r.ok) {
        setError(`Upload failed: ${r.status} ${await r.text()}`);
        return;
      }
      const j = (await r.json()) as { job_id: string; total: number };
      setJob({
        id: j.job_id,
        kind: "batch",
        status: "running",
        total: j.total,
        done: 0,
        failed_count: 0,
        error: null,
      });
    } finally {
      setSubmitting(false);
    }
  }

  const pct = job && job.total > 0 ? Math.round(((job.done + job.failed_count) / job.total) * 100) : 0;

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed py-10 text-sm transition-colors ${
          dragOver ? "border-foreground bg-accent" : "border-border hover:bg-accent"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        {file ? (
          <span className="font-medium">{file.name}</span>
        ) : (
          <>
            <span className="font-medium">Drop a CSV here, or click to choose</span>
            <span className="mt-1 text-xs text-muted-foreground">
              Required columns: email, name
            </span>
          </>
        )}
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!file || submitting}>
          {submitting ? "Uploading…" : "Start enrichment"}
        </Button>
        {file ? (
          <button
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={() => setFile(null)}
          >
            Clear
          </button>
        ) : null}
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      {job ? (
        <div className="rounded-md border border-border bg-accent/40 p-4 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-muted-foreground">{job.id}</span>
            <span className="font-medium capitalize">{job.status}</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-border">
            <div
              className="h-full bg-foreground transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {job.done} of {job.total} enriched
              {job.failed_count > 0 ? ` (${job.failed_count} failed)` : ""}
            </span>
            <span>{pct}%</span>
          </div>
          {job.status === "complete" ? (
            <div className="mt-3">
              <Link className="text-foreground underline" href="/people">
                View enriched people →
              </Link>
            </div>
          ) : null}
          {job.status === "failed" && job.error ? (
            <p className="mt-2 text-xs text-red-600">{job.error}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
