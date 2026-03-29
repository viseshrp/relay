import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { NewWorkflowPage } from "@/pages/NewWorkflowPage";
import { ProjectDetailPage } from "@/pages/ProjectDetailPage";
import { ProjectsListPage } from "@/pages/ProjectsListPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { RunsListPage } from "@/pages/RunsListPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsListPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/projects/:id/workflows/new" element={<NewWorkflowPage />} />
        <Route path="/runs" element={<RunsListPage />} />
        <Route path="/runs/:id" element={<RunDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
