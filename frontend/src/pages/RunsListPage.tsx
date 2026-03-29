import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listProjects } from "@/api/projects";
import { listRuns } from "@/api/runs";
import { wsClient } from "@/api/ws";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WorkflowStatus } from "@/types/api";
import { formatRunDuration } from "@/lib/utils";

const ALL_STATUSES: WorkflowStatus[] = [
  "queued",
  "running",
  "waiting_for_user",
  "completed",
  "completed_with_unresolved_findings",
  "failed",
  "cancelled",
];

const TERMINAL_STATUSES = new Set<WorkflowStatus>(["completed", "completed_with_unresolved_findings", "failed", "cancelled"]);

export function RunsListPage() {
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState("");
  const [selectedStatuses, setSelectedStatuses] = useState<WorkflowStatus[]>([]);
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const runsQuery = useQuery({
    queryKey: ["runs", projectId, selectedStatuses],
    queryFn: () => listRuns({ project_id: projectId || undefined, status: selectedStatuses.length > 0 ? selectedStatuses : undefined }),
  });

  useEffect(() => {
    wsClient.subscribeAllRuns();
    const unsubscribe = wsClient.subscribe((event) => {
      if (event.type === "workflow_status") {
        void queryClient.invalidateQueries({ queryKey: ["runs"] });
      }
    });
    return () => {
      unsubscribe();
      wsClient.unsubscribeAllRuns();
    };
  }, [queryClient]);

  if (projectsQuery.isLoading || runsQuery.isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Runs</h1>
        <p className="mt-1 text-sm text-muted-foreground">Track workflow progress across all registered projects.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr),auto]">
        <Select value={projectId} onValueChange={setProjectId}>
          <SelectTrigger>
            <SelectValue placeholder="All projects" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">All projects</SelectItem>
            {(projectsQuery.data ?? []).map((project) => (
              <SelectItem key={project.id} value={project.id}>
                {project.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">Status {selectedStatuses.length > 0 ? `(${selectedStatuses.length})` : ""}</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            {ALL_STATUSES.map((status) => (
              <DropdownMenuCheckboxItem
                key={status}
                checked={selectedStatuses.includes(status)}
                onCheckedChange={(checked) =>
                  setSelectedStatuses((current) =>
                    checked ? [...current, status] : current.filter((value) => value !== status),
                  )
                }
              >
                {status.replaceAll("_", " ")}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="border-t-0">
            <TableHead>Project</TableHead>
            <TableHead>Workflow</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Duration</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runsQuery.data?.items.map((run) => (
            <TableRow key={run.id}>
              <TableCell>{run.project_name}</TableCell>
              <TableCell>
                <Link to={`/runs/${run.id}`} className="text-primary">
                  {run.name}
                </Link>
              </TableCell>
              <TableCell>
                <StatusBadge status={run.status} />
              </TableCell>
              <TableCell>{new Date(run.created_at).toLocaleString()}</TableCell>
              <TableCell>{formatRunDuration(run.created_at, run.updated_at, TERMINAL_STATUSES.has(run.status))}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
