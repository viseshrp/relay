import { Alert, Button, Paper, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { RunEvent, RunNode } from "../types";
import { SafeMarkdown } from "./SafeMarkdown";

type Products = { artifacts: Array<{ id: string; name: string; digest: string; bytes: number; expires_at: string | null }>; queues: Array<{ scope: string; group: string; mode: string; state: string }>; environments?: Record<string, { name: string; url: string }> };

export function ActionsRunProducts({ runId, projectId, events, nodes }: { runId: string; projectId: string; events: RunEvent[]; nodes: RunNode[] }) {
  const [products, setProducts] = useState<Products>({ artifacts: [], queues: [] }); const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    async function load() { try { const result = await api<Products>(projectPath(`/api/runs/${encodeURIComponent(runId)}/products`, projectId)); if (active) { setProducts(result); setError(""); } } catch (e) { if (active) setError(errorMessage(e)); } }
    void load(); const timer = window.setInterval(() => { void load(); }, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, projectId]);
  const summaries = events.filter(item => item.type === "actions.summary");
  const annotations = events.filter(item => ["actions.error", "actions.warning", "actions.notice"].includes(item.type));
  const tolerated = nodes.filter(item => item.outcome === "failure" && item.conclusion === "success");
  return <Stack spacing={2}>
    {error && <Alert severity="error">{error}</Alert>}
    {tolerated.map(node => <Alert key={node.id} severity="warning">{node.scope_path} failed and continued by workflow policy.</Alert>)}
    {Object.entries(products.environments || {}).filter(([, item]) => /^https?:\/\//i.test(item.url)).map(([scope, item]) => <Button component="a" key={scope} href={item.url} target="_blank" rel="noopener noreferrer">Open {item.name} environment</Button>)}
    {products.queues.length > 0 && <Paper variant="outlined" sx={{ p: 2 }} aria-label="Concurrency queues"><Typography variant="h6">Concurrency queues</Typography>{products.queues.map(item => <Typography key={item.scope}>{item.scope}: {item.group} · {item.state} · {item.mode}</Typography>)}</Paper>}
    {products.artifacts.length > 0 && <Paper variant="outlined" sx={{ p: 2 }} aria-label="Named artifacts"><Typography variant="h6">Named artifacts</Typography>{products.artifacts.map(item => <Stack key={item.id} direction="row" spacing={1} sx={{ alignItems: "center" }}><Button component="a" href={projectPath(`/api/workflow-artifacts/${item.id}/download`, projectId)}>Download {item.name}</Button><Typography variant="body2">{item.bytes.toLocaleString()} bytes · SHA-256 {item.digest}{item.expires_at ? ` · expires ${new Date(item.expires_at).toLocaleString()}` : ""}</Typography></Stack>)}</Paper>}
    {annotations.map(item => <Alert key={item.id} severity={item.type === "actions.error" ? "error" : item.type === "actions.warning" ? "warning" : "info"}>{String(item.payload.message || "")}</Alert>)}
    {summaries.map(item => <Paper key={item.id} variant="outlined" sx={{ p: 2 }} aria-label="Step summary"><SafeMarkdown text={String(item.payload.markdown || "")} /></Paper>)}
  </Stack>;
}
