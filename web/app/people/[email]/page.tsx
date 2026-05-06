import Link from "next/link";
import { notFound } from "next/navigation";
import { getPerson, type PersonOut } from "@/lib/api";
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

      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold">Per-field confidence</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Each field shows the strongest source's effective confidence (source weight × signal confidence).
          </p>
        </CardHeader>
        <CardBody>
          <ul className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            {Object.entries(person.field_confidence).map(([field, conf]) => (
              <li key={field} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{field}</span>
                <ConfidenceBadge value={conf} />
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}
