import { NextRequest, NextResponse } from "next/server";
import { serverApiBase } from "@/lib/api";

/**
 * Catch-all API proxy. The browser hits /api/proxy/<api-path>; we forward
 * verbatim to the FastAPI service inside the docker network.
 *
 * Why proxy? It lets the browser stay on the same origin (no CORS) and lets
 * server-only headers stay server-only.
 */

async function forward(req: NextRequest, segments: string[]): Promise<Response> {
  const path = segments.map(encodeURIComponent).join("/");
  const search = req.nextUrl.search ?? "";
  const url = `${serverApiBase()}/${path}${search}`;

  const init: RequestInit = {
    method: req.method,
    headers: filterHeaders(req.headers),
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(url, init);
  const body = await upstream.arrayBuffer();
  return new NextResponse(body, {
    status: upstream.status,
    headers: passthroughHeaders(upstream.headers),
  });
}

function filterHeaders(h: Headers): Headers {
  const out = new Headers();
  for (const [k, v] of h.entries()) {
    const lk = k.toLowerCase();
    if (lk === "host" || lk === "connection" || lk.startsWith("x-forwarded-")) continue;
    out.set(k, v);
  }
  return out;
}

function passthroughHeaders(h: Headers): Headers {
  const out = new Headers();
  for (const [k, v] of h.entries()) {
    const lk = k.toLowerCase();
    if (lk === "content-encoding" || lk === "transfer-encoding") continue;
    out.set(k, v);
  }
  return out;
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
