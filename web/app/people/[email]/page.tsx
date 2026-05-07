import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getPerson,
  getRelationships,
  getSignalsByField,
  type PersonOut,
  type Relationship,
  type SignalRow,
} from "@/lib/api";
import { Card, CardBody, CardHeader, ConfidenceBadge } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function PersonDetail(props: {
  params: Promise<{ email: string }>;
}) {
  const { email } = await props.params;
  const decoded = decodeURIComponent(email);

  let person: PersonOut;
  try {
    person = await getPerson(decoded);
  } catch (e) {
    if (String(e).includes("404")) notFound();
    throw e;
  }

  let relationships: Relationship[] = [];
  try {
    relationships = await getRelationships(decoded);
  } catch {
    // non-fatal; just hide the card
  }

  let signalsByField: Record<string, SignalRow[]> = {};
  try {
    signalsByField = await getSignalsByField(decoded);
  } catch {
    // non-fatal
  }

  return (
    <div className="space-y-6">
      <Link href="/people" className="text-sm text-muted-foreground hover:text-foreground">
        ← Back to people
      </Link>

      <Card>
        <CardBody className="flex items-start gap-5">
          {person.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={person.avatar_url}
              alt=""
              className="h-20 w-20 rounded-full bg-accent object-cover"
            />
          ) : (
            <div className="h-20 w-20 rounded-full bg-accent" />
          )}
          <div className="flex-1">
            <h1 className="text-2xl font-semibold tracking-tight">{person.name}</h1>
            <p className="text-sm text-muted-foreground">{person.email}</p>
            {person.title || person.company ? (
              <p className="mt-2 text-base">
                {person.title ? <span className="font-medium">{person.title}</span> : null}
                {person.title && person.company ? " · " : ""}
                {person.company}
              </p>
            ) : null}
            {person.location ? (
              <p className="mt-1 text-sm text-muted-foreground">{person.location}</p>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2">
              {person.sources.map((s) => (
                <span
                  key={s}
                  className="rounded-full border border-border bg-accent px-2.5 py-0.5 text-xs"
                >
                  {s}
                </span>
              ))}
              <ConfidenceBadge value={person.confidence} />
            </div>
            {person.bio ? (
              <p className="mt-4 max-w-prose text-sm">{person.bio}</p>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              {person.linkedin_url ? (
                <a className="underline" href={person.linkedin_url} target="_blank" rel="noreferrer">
                  LinkedIn
                </a>
              ) : null}
              {person.github_url ? (
                <a className="underline" href={person.github_url} target="_blank" rel="noreferrer">
                  GitHub
                </a>
              ) : null}
              {person.twitter_url ? (
                <a className="underline" href={person.twitter_url} target="_blank" rel="noreferrer">
                  Twitter / X
                </a>
              ) : null}
              {person.company_domain ? (
                <a className="underline" href={`https://${person.company_domain}`} target="_blank" rel="noreferrer">
                  {person.company_domain}
                </a>
              ) : null}
            </div>
          </div>
          {person.company_logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={person.company_logo_url}
              alt=""
              className="h-12 w-12 rounded-md bg-accent object-contain"
            />
          ) : null}
        </CardBody>
      </Card>

      {person.company_description ? (
        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold">Company</h2>
          </CardHeader>
          <CardBody>
            <p className="text-sm">{person.company_description}</p>
          </CardBody>
        </Card>
      ) : null}

      {relationships.length > 0 ? (
        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold">Relationships</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Other people in the dataset connected by company, email domain, university, or city.
            </p>
          </CardHeader>
          <CardBody className="p-0">
            <ul>
              {relationships.map((r, i) => (
                <li
                  key={`${r.kind}-${r.other.email}-${i}`}
                  className="flex items-center justify-between border-b border-border px-5 py-3 last:border-0"
                >
                  <Link
                    href={`/people/${encodeURIComponent(r.other.email)}`}
                    className="flex items-center gap-3"
                  >
                    {r.other.avatar_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={r.other.avatar_url}
                        alt=""
                        className="h-8 w-8 rounded-full bg-accent object-cover"
                      />
                    ) : (
                      <div className="h-8 w-8 rounded-full bg-accent" />
                    )}
                    <span>
                      <span className="block font-medium">{r.other.name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {r.other.email}
                        {r.other.company ? ` · ${r.other.company}` : ""}
                      </span>
                    </span>
                  </Link>
                  <span className="flex items-center gap-2">
                    <span className="rounded-full border border-border bg-accent px-2.5 py-0.5 text-[11px]">
                      {r.kind.replace(/_/g, " ")}
                    </span>
                    <ConfidenceBadge value={r.confidence} />
                  </span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold">Per-field confidence & sources</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Each field shows the materialized confidence (source weight × signal confidence) and every source that emitted a value for that field. Hover a source chip to see what it claimed.
          </p>
        </CardHeader>
        <CardBody className="p-0">
          <ul>
            {Object.entries(person.field_confidence).map(([field, conf]) => {
              const contributors = signalsByField[field] ?? [];
              return (
                <li
                  key={field}
                  className="flex items-start justify-between gap-4 border-b border-border px-5 py-3 last:border-0"
                >
                  <div className="flex-1">
                    <div className="text-sm font-medium">{field}</div>
                    {contributors.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {contributors.map((c, i) => (
                          <span
                            key={`${c.source}-${i}`}
                            title={c.value ?? "(null)"}
                            className="rounded-full border border-border bg-accent px-2 py-0.5 font-mono text-[11px]"
                          >
                            {c.source}
                            <span className="ml-1 text-muted-foreground">
                              {c.confidence.toFixed(2)}
                            </span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-1 text-xs text-muted-foreground">
                        no source attempted this field
                      </div>
                    )}
                  </div>
                  <ConfidenceBadge value={conf} />
                </li>
              );
            })}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}
