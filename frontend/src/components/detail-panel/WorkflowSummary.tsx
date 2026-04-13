import type { RunDetail } from "@/types/api";

import { StatusBadge } from "@/components/shared/StatusBadge";
import { Card } from "@/components/ui/card";

export function WorkflowSummary({ run }: { run: RunDetail }) {
  return (
    <Card className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">{run.name}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{run.project_name}</p>
        </div>
        <StatusBadge status={run.status} />
      </div>
      <dl className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
        <div>
          <dt className="font-medium text-foreground">Branch</dt>
          <dd>{run.branch ?? "Not created yet"}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground">Created</dt>
          <dd>{new Date(run.created_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground">Context Paths</dt>
          <dd>{run.context_paths.length ? run.context_paths.join(", ") : "None selected"}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground">Review Loop</dt>
          <dd>
            {run.review_fix_loop_count}/{run.review_fix_loop_limit}
          </dd>
        </div>
      </dl>
    </Card>
  );
}
