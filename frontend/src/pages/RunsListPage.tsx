import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listProjects } from "@/api/projects";
import { listRuns } from "@/api/runs";
import { Table } from "@/components/ui/table";
import { Select } from "@/components/ui/select";

export function RunsListPage() {
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("");
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const runsQuery = useQuery({
    queryKey: ["runs", projectId, status],
    queryFn: () => listRuns({ project_id: projectId || undefined, status: status || undefined }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Runs</h1>
        <p className="mt-1 text-sm text-muted-foreground">Track workflow progress across all registered projects.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Select value={projectId} onChange={(event) => setProjectId(event.target.value)} options={[{ label: "All projects", value: "" }, ...(projectsQuery.data ?? []).map((project) => ({ label: project.name, value: project.id }))]} />
        <Select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          options={[
            { label: "All statuses", value: "" },
            { label: "Queued", value: "queued" },
            { label: "Running", value: "running" },
            { label: "Waiting", value: "waiting_for_user" },
            { label: "Completed", value: "completed" },
            { label: "Failed", value: "failed" },
            { label: "Cancelled", value: "cancelled" },
          ]}
        />
      </div>
      <Table>
        <thead className="bg-secondary/60">
          <tr>
            <th className="px-4 py-3 text-left">Project</th>
            <th className="px-4 py-3 text-left">Workflow</th>
            <th className="px-4 py-3 text-left">Status</th>
            <th className="px-4 py-3 text-left">Created</th>
          </tr>
        </thead>
        <tbody>
          {runsQuery.data?.items.map((run) => (
            <tr key={run.id} className="border-t border-border">
              <td className="px-4 py-3">{run.project_name}</td>
              <td className="px-4 py-3">
                <Link to={`/runs/${run.id}`} className="text-primary">
                  {run.name}
                </Link>
              </td>
              <td className="px-4 py-3">{run.status}</td>
              <td className="px-4 py-3">{new Date(run.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}
