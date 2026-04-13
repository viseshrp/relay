import { apiRequest } from "@/api/client";
import type { FileTreeNode, Project, ProjectSettings } from "@/types/api";

export function listProjects() {
  return apiRequest<Project[]>("/projects");
}

export function createProject(payload: { path: string; name?: string }) {
  return apiRequest<Project>("/projects", { method: "POST", body: JSON.stringify(payload) });
}

export function getProject(projectId: string) {
  return apiRequest<Project>(`/projects/${projectId}`);
}

export function updateProject(projectId: string, payload: { name: string }) {
  return apiRequest<Project>(`/projects/${projectId}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteProject(projectId: string) {
  return apiRequest<void>(`/projects/${projectId}`, { method: "DELETE" });
}

export function getProjectFiles(projectId: string) {
  return apiRequest<FileTreeNode[]>(`/projects/${projectId}/files`);
}

export function getProjectSettings(projectId: string) {
  return apiRequest<ProjectSettings>(`/projects/${projectId}/settings`);
}

export function updateProjectSettings(projectId: string, payload: Partial<ProjectSettings>) {
  return apiRequest<ProjectSettings>(`/projects/${projectId}/settings`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
