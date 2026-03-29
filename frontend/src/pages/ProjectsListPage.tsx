import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { createProject, listProjects } from "@/api/projects";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/shared/StatusBadge";

export function ProjectsListPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const { data } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const createMutation = useMutation({
    mutationFn: () => createProject({ path, name: name || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setOpen(false);
      setPath("");
      setName("");
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-semibold">Projects</h1>
          <p className="mt-1 text-sm text-muted-foreground">Register repositories and local folders for Relay workflows.</p>
        </div>
        <Button onClick={() => setOpen(true)}>Add Project</Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {data?.map((project) => (
          <Link key={project.id} to={`/projects/${project.id}`}>
            <Card className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">{project.name}</h2>
                  <p className="text-sm text-muted-foreground">{project.path}</p>
                </div>
                <StatusBadge status={project.is_git_repo ? "succeeded" : "queued"} />
              </div>
              <p className="text-sm text-muted-foreground">Active runs: {project.active_run_count}</p>
            </Card>
          </Link>
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Add Project</h2>
          <Input placeholder="Absolute path" value={path} onChange={(event) => setPath(event.target.value)} />
          <Input placeholder="Optional display name" value={name} onChange={(event) => setName(event.target.value)} />
          <Button onClick={() => createMutation.mutate()}>Save</Button>
        </div>
      </Dialog>
    </div>
  );
}
