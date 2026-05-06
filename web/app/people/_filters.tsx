"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Input } from "@/components/ui";

type Initial = {
  min_confidence: number | undefined;
  company: string;
  location: string;
  sort_by: "confidence" | "name" | "enriched_at";
};

export default function PeopleFilters({ initial }: { initial: Initial }) {
  const router = useRouter();
  const sp = useSearchParams();
  const [state, setState] = useState(initial);

  function apply(next: Partial<Initial>) {
    const merged = { ...state, ...next };
    setState(merged);
    const q = new URLSearchParams(sp.toString());
    if (merged.min_confidence !== undefined && !Number.isNaN(merged.min_confidence)) {
      q.set("min_confidence", String(merged.min_confidence));
    } else {
      q.delete("min_confidence");
    }
    if (merged.company) q.set("company", merged.company);
    else q.delete("company");
    if (merged.location) q.set("location", merged.location);
    else q.delete("location");
    if (merged.sort_by) q.set("sort_by", merged.sort_by);
    router.push(`/people?${q.toString()}`);
  }

  return (
    <div className="flex items-end gap-3">
      <div className="w-32">
        <label className="text-xs text-muted-foreground">Min confidence</label>
        <Input
          type="number"
          step="0.05"
          min="0"
          max="1"
          defaultValue={state.min_confidence ?? ""}
          onBlur={(e) =>
            apply({
              min_confidence:
                e.target.value === "" ? undefined : parseFloat(e.target.value),
            })
          }
        />
      </div>
      <div className="w-44">
        <label className="text-xs text-muted-foreground">Company</label>
        <Input
          placeholder="Stripe"
          defaultValue={state.company}
          onBlur={(e) => apply({ company: e.target.value })}
        />
      </div>
      <div className="w-44">
        <label className="text-xs text-muted-foreground">Location</label>
        <Input
          placeholder="San Francisco"
          defaultValue={state.location}
          onBlur={(e) => apply({ location: e.target.value })}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground">Sort</label>
        <select
          className="block h-10 w-40 rounded-md border border-border bg-background px-2 text-sm"
          value={state.sort_by}
          onChange={(e) =>
            apply({ sort_by: e.target.value as Initial["sort_by"] })
          }
        >
          <option value="confidence">Confidence</option>
          <option value="name">Name</option>
          <option value="enriched_at">Enriched at</option>
        </select>
      </div>
    </div>
  );
}
