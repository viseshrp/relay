import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { createProject, listProjects } from "@/api/projects";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

export function ProjectsListPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const createMutation = useMutation({
    mutationFn: () => createProject({ path, name: name || undefined }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      setOpen(false);
      setPath("");
      setName("");
    },
  });

  if (projectsQuery.isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

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
        {projectsQuery.data?.map((project) => (
          <Link key={project.id} to={`/projects/${project.id}`}>
            <Card className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">{project.name}</h2>
                  <p className="text-sm text-muted-foreground">{project.path}</p>
                </div>
                <Badge variant={project.is_git_repo ? "default" : "secondary"}>{project.is_git_repo ? "Git" : "Local"}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">Active runs: {project.active_run_count}</p>
            </Card>
          </Link>
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Project</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <label className="space-y-2 text-sm font-medium">
              <span>Absolute path</span>
              <Input placeholder="Absolute path" value={path} onChange={(event) => setPath(event.target.value)} />
            </label>
            <label className="space-y-2 text-sm font-medium">
              <span>Display name</span>
              <Input placeholder="Optional display name" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
          </div>
          <DialogFooter className="mt-4">
            <Button onClick={() => createMutation.mutate()}>Add</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
