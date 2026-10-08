import { HelpControl, HelpLabel, HelpSelectField, HelpTextField } from "./HelpTip";
import { Alert, Box, Button, CircularProgress, FormControlLabel, List, ListItemButton, ListItemText, MenuItem, Paper, Stack, Switch, Typography } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { AgentsResponse, OwnerSettings, ProjectDefaultOverrides, ProjectRecord, ProjectSettingsResponse, SettingsResponse } from "../types";
import { PathDisplay } from "./PathDisplay";
import { StorageSettings } from "./StorageSettings";
import { DefaultSettingsForm } from "./DefaultSettingsForm";

import type { SettingsSection } from "../onboarding";

const sections = ["Global defaults", "Project defaults", "Server and account", "Notifications", "Storage", "Welcome and guided tour"] as const;
type Section = typeof sections[number];
interface Props {
  project: ProjectRecord | undefined;
  requestProject: string | null;
  notifications: boolean;
  onToggleNotifications: () => Promise<void>;
  tourSection?: SettingsSection | null;
  onShowWelcome: () => void;
  onShowTour: () => void;
  onResetOnboarding: () => boolean;
  onNavigationReady: (callback: (() => Promise<void>) | null) => void;
}

export function SettingsPage({ project, requestProject, notifications, onToggleNotifications, onNavigationReady, tourSection, onShowWelcome, onShowTour, onResetOnboarding }: Props) {
  const [onboardingNotice, setOnboardingNotice] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("Global defaults");
  useEffect(() => { if (tourSection) setSection(tourSection); }, [tourSection]);
  const [response, setResponse] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<OwnerSettings | null>(null);
  const [agents, setAgents] = useState<AgentsResponse | null>(null);
  const [projectResponse, setProjectResponse] = useState<ProjectSettingsResponse | null>(null);
  const [overrides, setOverrides] = useState<ProjectDefaultOverrides>({});
  const [effective, setEffective] = useState<OwnerSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const preview = useRef<AbortController | null>(null);
  const dirty = Boolean(response && draft && JSON.stringify(response.settings) !== JSON.stringify(draft)) || Boolean(projectResponse && JSON.stringify(projectResponse.overrides) !== JSON.stringify(overrides));

  const preventLeave = useCallback(async () => { if (dirty) throw new Error("Save or discard your settings before leaving."); }, [dirty]);
  useEffect(() => { onNavigationReady(preventLeave); return () => onNavigationReady(null); }, [onNavigationReady, preventLeave]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null); setNotice(null);
    void Promise.allSettled([
      api<SettingsResponse>("/api/settings", { signal: controller.signal }),
      api<AgentsResponse>(projectPath("/api/agents", requestProject), { signal: controller.signal }),
      project ? api<ProjectSettingsResponse>(projectPath("/api/projects/defaults", requestProject), { signal: controller.signal }) : Promise.resolve(null),
    ]).then(([global, tools, local]) => {
      if (controller.signal.aborted) return;
      if (global.status === "rejected") {
        setResponse(null); setDraft(null); setError(errorMessage(global.reason)); return;
      }
      const projectSettings = local.status === "fulfilled" ? local.value : null;
      setResponse(global.value); setDraft(global.value.settings); setAgents(tools.status === "fulfilled" ? tools.value : null); setProjectResponse(projectSettings); setOverrides(projectSettings?.overrides ?? {}); setEffective(projectSettings?.effective ?? null);
      const failures = [tools, local].filter((result) => result.status === "rejected");
      setError(failures.map((result) => result.status === "rejected" ? errorMessage(result.reason) : "").join(" ") || null);
    }).catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); preview.current?.abort(); };
  }, [project?.id, requestProject, revision]);

  function updateOverrides(values: ProjectDefaultOverrides) {
    setOverrides(values); setNotice(null); setError(null); preview.current?.abort();
    const controller = new AbortController(); preview.current = controller;
    void api<{ effective: OwnerSettings }>(projectPath("/api/projects/defaults", requestProject), { method: "POST", signal: controller.signal, body: JSON.stringify({ overrides: values, preview: true }) })
      .then((result) => { if (!controller.signal.aborted) setEffective(result.effective); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); });
  }
  async function save(projectOnly = false): Promise<void> {
    if (!draft || !response) return;
    setBusy(true); setError(null); setNotice(null);
    preview.current?.abort();
    try {
      if (projectOnly && projectResponse) {
        const result = await api<ProjectSettingsResponse>(projectPath("/api/projects/defaults", requestProject), { method: "POST", body: JSON.stringify({ overrides, revision: projectResponse.revision }) });
        setProjectResponse(result); setOverrides(result.overrides); setEffective(result.effective); setNotice("Project defaults saved. Future runs inherit these choices.");
      } else {
        const result = await api<SettingsResponse>("/api/settings", { method: "POST", body: JSON.stringify({ settings: draft, revision: response.revision }) });
        const restart = ["host", "port", "workers", "login_required"] as const;
        const changed = restart.some((key) => result.settings[key] !== response.settings[key]);
        setResponse(result); setDraft(result.settings); setNotice(changed ? "Settings saved. Restart Relay to apply server and login changes." : "Global defaults saved. Future runs inherit these choices.");
        if (project) {
          const local = await api<ProjectSettingsResponse>(projectPath("/api/projects/defaults", requestProject));
          setProjectResponse(local);
          if (projectResponse && JSON.stringify(projectResponse.overrides) !== JSON.stringify(overrides)) {
            const pending = await api<{ effective: OwnerSettings }>(projectPath("/api/projects/defaults", requestProject), { method: "POST", body: JSON.stringify({ overrides, preview: true }) });
            setEffective(pending.effective);
          } else setEffective(local.effective);
        }
      }
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }
  function discard() { setDraft(response?.settings ?? null); setOverrides(projectResponse?.overrides ?? {}); setEffective(projectResponse?.effective ?? null); setNotice(null); setError(null); preview.current?.abort(); }

  if (loading) return <Box className="loading-panel"><CircularProgress aria-label="Loading settings" /></Box>;
  if (!response || !draft) return <Stack spacing={2}><Alert severity="error">{error ?? "Settings could not be loaded."}</Alert><Button onClick={() => setRevision((value) => value + 1)}>Retry settings</Button></Stack>;
  const projectView = section === "Project defaults";
  const editable = section === "Global defaults" || projectView || section === "Server and account";
  return <Box className="actions-layout settings-layout">
    <Box component="nav" aria-label="Settings sections" data-tour="settings-navigation" className="actions-sidebar"><Typography variant="h6" sx={{ p: 2 }}>Settings</Typography><List>{sections.map((name) => <ListItemButton key={name} aria-current={name === section ? "page" : undefined} selected={name === section} onClick={() => { setSection(name); setNotice(null); }}><ListItemText primary={name} /></ListItemButton>)}</List></Box>
    <Paper component="section" aria-label={section} variant="outlined" className="settings-content" data-tour={section === "Storage" ? "storage" : undefined}>
      <Stack spacing={3}>
        <Box><Typography variant="h5">{section}</Typography><Typography color="text.secondary" sx={{ mt: 1 }}>{projectView ? `Overrides for ${project?.display_name ?? "the selected project"}. Turn an override off to inherit the saved global value.` : section === "Global defaults" ? "Defaults for this Relay installation, across all projects. Saved runs keep their captured choices." : section === "Server and account" ? "Local access and server settings. Changes apply after restarting Relay." : section === "Notifications" ? "Notification preferences for this browser." : section === "Storage" ? "Installation folders and retained project data." : "Learn Relay at your own pace. These preferences belong to this browser."}</Typography></Box>
        {error && <Alert severity="error" action={<Button disabled={busy} onClick={() => setRevision((value) => value + 1)}>Reload settings</Button>}>{error}</Alert>}
        {notice && <Alert severity="success">{notice}</Alert>}
        {section === "Global defaults" && <><Alert severity="info">Models resolve from the job, run override, workflow, then project and global defaults. Thinking effort and permissions respect explicit job choices and exact model matches.</Alert><DefaultSettingsForm settings={draft} agents={agents?.agents ?? []} onChange={(values) => { setDraft(values); setNotice(null); }} project={requestProject} disabled={busy} tourActive={Boolean(tourSection)} /></>}
        {section === "Global defaults" && !agents && <Alert severity="info">Open a project with available agent discovery to choose models and thinking effort. Other global settings remain editable.</Alert>}
        {projectView && (project && effective ? <DefaultSettingsForm settings={effective} agents={agents?.agents ?? []} onChange={setEffective} project={requestProject} disabled={busy} overrides={overrides} onOverrides={updateOverrides} /> : <Alert severity="info">{project ? "Project defaults could not be loaded. Reload settings to try again." : "Open a project to set its overrides."}</Alert>)}
        {section === "Server and account" && <Stack spacing={3}>
          <Box><Typography variant="h6">Local account</Typography><Typography>{response.active_login_required ? `Signed in as ${response.username}. Login is currently required.` : "Login is disabled. This browser uses local access without signing in."}</Typography></Box>
          <HelpControl topic="login" tour><FormControlLabel control={<Switch checked={draft.login_required} disabled={busy} onChange={(_event, checked) => setDraft({ ...draft, login_required: checked })} />} label="Require login" /></HelpControl>
          <Alert severity="info">Restart Relay after changing login, address, port, or workers. Command-line flags override saved values for that process. Your existing account and data remain saved.</Alert>
          <HelpSelectField compact topic="host" tour label="Loopback address" fullWidth value={draft.host} disabled={busy} onChange={(event) => setDraft({ ...draft, host: event.target.value })}>{["127.0.0.1", "localhost", "::1"].map((host) => <MenuItem key={host} value={host}>{host}</MenuItem>)}</HelpSelectField>
          <Box className="field-grid server-fields"><HelpTextField topic="port" tour label="Port" type="number" value={draft.port} disabled={busy} onChange={(event) => setDraft({ ...draft, port: Number(event.target.value) })} slotProps={{ htmlInput: { min: 1, max: 65535 } }}  /><HelpTextField topic="workers" tour label="Workers" type="number" value={draft.workers} disabled={busy} onChange={(event) => setDraft({ ...draft, workers: Number(event.target.value) })} slotProps={{ htmlInput: { min: 1 } }} helperText="Local jobs that can run at once. Git write locks still apply."  /></Box>
        </Stack>}
        {section === "Notifications" && <Stack spacing={2}><Typography>Notifications cover waiting runs and completed runs across every project in this browser. They contain no questions or agent output.</Typography><HelpControl topic="notifications" tour><FormControlLabel control={<Switch checked={notifications} onChange={() => void onToggleNotifications()} />} label="Desktop notifications" /></HelpControl><Typography variant="body2" color="text.secondary">Enabling notifications asks this browser for permission. Other browsers keep their own preference.</Typography></Stack>}
        {section === "Storage" && <Stack spacing={3}><Box component="section" aria-label="Installation folders"><Typography variant="h6" sx={{ mb: 1 }}>Installation folders</Typography><Box component="dl" className="data-rows">{Object.entries(response.paths).map(([name, path]) => { const label = name === "prompts" ? "Shared instructions" : name.charAt(0).toUpperCase() + name.slice(1); return <Box key={name} className="data-row"><Typography component="dt">{label}</Typography><Box component="dd"><PathDisplay path={path} label={label} /></Box></Box>; })}</Box></Box><Typography variant="body2" color="text.secondary">Workflow files stay in each project's .relay folder. These folders hold installation settings, shared instructions, run history, working copies, and process logs.</Typography>{project && <StorageSettings project={project} requestProject={requestProject} />}</Stack>}
        {section === "Welcome and guided tour" && <Stack spacing={2} data-tour="onboarding">
          <Typography>Welcome slides introduce projects, workflows, live logs, and defaults. The spotlight tour explains controls without changing your settings or running jobs.</Typography>
          <HelpLabel topic="onboarding">Replay or reset onboarding</HelpLabel>
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}><Button variant="outlined" onClick={onShowWelcome}>Replay welcome slides</Button><Button variant="outlined" onClick={onShowTour}>Replay guided tour</Button><Button onClick={() => setOnboardingNotice(onResetOnboarding() ? "Onboarding reset. The welcome slides and tour will appear the next time you open or reload Relay in this browser." : "This browser cannot save onboarding preferences. You can still replay the slides or tour here.")}>Reset onboarding</Button></Stack>
          {onboardingNotice && <Alert severity="info">{onboardingNotice}</Alert>}
        </Stack>}
        {editable && <Stack direction="row" spacing={1} className="settings-save"><Button variant="contained" disabled={busy || (projectView && !projectResponse)} onClick={() => void save(projectView)}>{busy ? "Saving…" : projectView ? "Save project defaults" : "Save global settings"}</Button><Button disabled={busy || !dirty} onClick={discard}>Discard changes</Button></Stack>}
      </Stack>
    </Paper>
  </Box>;
}
