import Link from "next/link";
import { listPeople } from "@/lib/api";
import { Card, CardBody, ConfidenceBadge } from "@/components/ui";
import PeopleFilters from "./_filters";

export const dynamic = "force-dynamic";

export default async function PeoplePage(props: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await props.searchParams;

  const min_confidence = numParam(sp.min_confidence);
  const company = strParam(sp.company);
  const location = strParam(sp.location);
  const sort_by = (strParam(sp.sort_by) as "confidence" | "name" | "enriched_at" | undefined) ?? "confidence";

  const data = await listPeople({
    min_confidence,
    company,
    location,
    sort_by,
    limit: 200,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">People</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data.total} enriched record{data.total === 1 ? "" : "s"}
            {min_confidence !== undefined ? ` · confidence ≥ ${min_confidence}` : ""}
          </p>
        </div>
        <PeopleFilters
          initial={{
            min_confidence,
            company: company ?? "",
            location: location ?? "",
            sort_by,
          }}
        />
      </div>

      <Card>
        <CardBody className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Company</th>
                <th className="px-4 py-3 font-medium">Location</th>
                <th className="px-4 py-3 font-medium">Sources</th>
                <th className="px-4 py-3 font-medium text-right">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                    No people match.
                  </td>
                </tr>
              ) : (
                data.items.map((p) => (
                  <tr
                    key={p.email}
                    className="border-b border-border last:border-0 hover:bg-accent/40"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/people/${encodeURIComponent(p.email)}`}
                        className="flex items-center gap-3"
                      >
                        {p.avatar_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={p.avatar_url}
                            alt=""
                            className="h-8 w-8 rounded-full bg-accent object-cover"
                          />
                        ) : (
                          <div className="h-8 w-8 rounded-full bg-accent" />
                        )}
                        <span>
                          <span className="block font-medium text-foreground">{p.name}</span>
                          <span className="block text-xs text-muted-foreground">{p.email}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {p.company ?? <span className="text-muted-foreground">—</span>}
                      {p.title ? (
                        <span className="block text-xs text-muted-foreground">{p.title}</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {p.location ?? <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {p.sources.map((s) => (
                          <span
                            key={s}
                            className="rounded-full border border-border bg-accent px-2 py-0.5 text-[11px] text-foreground"
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <ConfidenceBadge value={p.confidence} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </div>
  );
}

function strParam(v: string | string[] | undefined): string | undefined {
  if (Array.isArray(v)) return v[0] || undefined;
  return v && v.length ? v : undefined;
}

function numParam(v: string | string[] | undefined): number | undefined {
  const s = strParam(v);
  if (s === undefined) return undefined;
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : undefined;
}
