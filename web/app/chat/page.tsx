"use client";

import { useState } from "react";
import { Button, Card, CardBody, Input } from "@/components/ui";

type Turn = {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
};

const SUGGESTIONS = [
  "Who do we know the least about?",
  "Who works in fintech?",
  "Find early-stage founders in the dataset.",
  "Who in San Francisco should we reach out to first?",
  "Which of these people might know each other?",
];

export default function ChatPage() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);

  async function send(text: string) {
    if (!text.trim() || pending) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", content: text }]);
    setPending(true);
    try {
      const r = await fetch("/api/proxy/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!r.ok) {
        const errText = await r.text();
        setTurns((t) => [
          ...t,
          { role: "assistant", content: `Error: ${r.status} ${errText}` },
        ]);
        return;
      }
      const data = await r.json();
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: data.answer ?? "(no answer)",
          tools: (data.tool_calls ?? []).map((c: { name: string }) => c.name),
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ask questions about the enriched dataset. Claude reads the database with structured tools — every claim is grounded in real records.
        </p>
      </div>

      {turns.length === 0 ? (
        <Card>
          <CardBody>
            <p className="mb-3 text-sm text-muted-foreground">Try one of these:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-border bg-accent px-3 py-1 text-sm hover:bg-foreground hover:text-background"
                >
                  {s}
                </button>
              ))}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <div className="space-y-4">
        {turns.map((t, i) => (
          <div
            key={i}
            className={`whitespace-pre-wrap rounded-md border border-border p-4 text-sm ${
              t.role === "user" ? "bg-accent/40" : "bg-background"
            }`}
          >
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t.role}
              {t.tools && t.tools.length ? (
                <span className="ml-2 font-mono normal-case text-[10px]">
                  tools: {t.tools.join(", ")}
                </span>
              ) : null}
            </div>
            <div className="prose prose-sm max-w-none">{t.content}</div>
          </div>
        ))}
        {pending ? (
          <div className="rounded-md border border-border bg-background p-4 text-sm text-muted-foreground">
            Thinking…
          </div>
        ) : null}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="flex items-center gap-2"
      >
        <Input
          placeholder="Ask anything about your users…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={pending}
        />
        <Button type="submit" disabled={pending || !input.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}
