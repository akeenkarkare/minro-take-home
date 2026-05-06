import UploadPanel from "./_components/upload-panel";
import { Card, CardBody, CardHeader } from "@/components/ui";
import Link from "next/link";

export default function Home() {
  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Enrich your user list</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Upload a CSV with <code className="rounded bg-accent px-1 py-0.5 font-mono text-xs">email,name</code> columns. Each row is enriched in the background — when the job finishes, head to <Link className="underline" href="/people">People</Link> to browse the results, or open <Link className="underline" href="/chat">Chat</Link> to ask questions over the dataset.
        </p>
      </section>

      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold">Upload CSV</h2>
        </CardHeader>
        <CardBody>
          <UploadPanel />
        </CardBody>
      </Card>
    </div>
  );
}
