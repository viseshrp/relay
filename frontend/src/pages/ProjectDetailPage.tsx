import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { getProject, getProjectSettings } from "@/api/projects";
import { listRuns } from "@/api/runs";
import { Card } from "@/components/ui/card";
import { Table } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";

export function ProjectDetailPage() {
  const { id = "" } = useParams();
  const [tab, setTab] = useState("overview");
  const projectQuery = useQuery({ queryKey: ["project", id], queryFn: () => getProject(id) });
  const runsQuery = useQuery({ queryKey: ["runs", "project", id], queryFn: () => listRuns({ project_id: id }) });
  const settingsQuery = useQuery({ queryKey: ["project-settings", id], queryFn: () => getProjectSettings(id) });

  if (!projectQuery.data) {
    return null;
  }

  return (
    <Tabs
      value={tab}
      onValueChange={setTab}
      tabs={[
        {
          value: "overview",
          label: "Overview",
          content: (
            <Card className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-3xl font-semibold">{projectQuery.data.name}</h1>
                  <p className="text-sm text-muted-foreground">{projectQuery.data.path}</p>
                </div>
                <Button asChild>
                  <Link to={`/projects/${id}/workflows/new`}>New Workflow</Link>
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">Git branch: {projectQuery.data.current_branch ?? "Not a git repository"}</p>
            </Card>
          ),
        },
        {
          value: "runs",
          label: "Runs",
          content: (
            <Table>
              <thead className="bg-secondary/60">
                <tr>
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Created</th>
                </tr>
              </thead>
              <tbody>
                {runsQuery.data?.items.map((run) => (
                  <tr key={run.id} className="border-t border-border">
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
          ),
        },
        {
          value: "configuration",
          label: "Configuration",
          content: <Card><pre className="text-sm">{JSON.stringify(settingsQuery.data, null, 2)}</pre></Card>,
        },
      ]}
    />
  );
}
