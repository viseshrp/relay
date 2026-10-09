import { Alert, Box, Button, FormControl, FormControlLabel, InputLabel, MenuItem, Paper, Select, Stack, Switch, TextField, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { useEffect, useMemo, useRef, useState } from "react";
import { activityRows, relativeActivityText, type ActivityMessage } from "../activity";
import { ansiSpans, commandLines, type AnsiStyle } from "../job";
import { stageLabel } from "../navigation";
import type { RunEvent, RunNode } from "../types";
import { SafeMarkdown } from "./SafeMarkdown";
import { errorMessage } from "../api";

export function toolStatus(status: string): { icon: string; text: string } {
  if (["completed", "done", "success", "succeeded"].includes(status.toLowerCase())) return { icon: "✓", text: "Completed" };
  if (["failed", "error", "canceled", "cancelled"].includes(status.toLowerCase())) return { icon: "✕", text: "Failed" };
  if (["pending", "waiting"].includes(status.toLowerCase())) return { icon: "○", text: "Waiting" };
  if (["in_progress", "running", "executing", "started"].includes(status.toLowerCase())) return { icon: "◷", text: "In progress" };
  return { icon: "○", text: "Status unavailable" };
}

export function ActivityMessageView({ message, workingFolder, timestamps = true, expanded = false }: { message: ActivityMessage; workingFolder?: string; timestamps?: boolean; expanded?: boolean }) {
  const text = relativeActivityText(message.text, workingFolder);
  const attribution = `${stageLabel(message.scope)} · ${message.agent ? stageLabel(message.agent) : message.kind.startsWith("command.") ? "Command" : "Agent"}${message.attempt !== null ? ` · Attempt ${message.attempt}` : ""}`;
  const tool = message.tool;
  const status = tool ? toolStatus(tool.status) : null;
  return <Paper variant="outlined" component="article" className="activity-message"
    sx={message.kind.startsWith("agent.") ? { color: "secondary.dark", bgcolor: (theme) => alpha(theme.palette.secondary.main, 0.055) } : undefined}>
    <Typography variant="caption" color="text.secondary">{attribution}{timestamps ? ` · ${new Date(message.timestamp).toLocaleTimeString()}` : ""}</Typography>
    {tool && status ? <Box component="details" className="activity-tool" open={expanded || undefined}>
      <Box component="summary"><Box component="span" aria-hidden sx={{ mr: 1 }}>{status.icon}</Box>
        {relativeActivityText(tool.title, workingFolder)} · {status.text}</Box>
      {tool.input && <Box component="pre" className="activity-text">{relativeActivityText(tool.input, workingFolder)}</Box>}
      {tool.output && <Box component="pre" className="activity-text">{relativeActivityText(tool.output, workingFolder)}</Box>}
      {!tool.input && !tool.output && <Typography>No output was included for this tool.</Typography>}
    </Box> : message.kind === "agent.thought" ? <Box component="details" open={expanded || undefined}>
      <Box component="summary">Thoughts</Box><SafeMarkdown text={text} />
    </Box> : ["agent.message", "agent.plan"].includes(message.kind) ? <SafeMarkdown text={text} />
      : <Box component="pre" className="activity-text">{ansiSpans(text).map((span, index) => <Box component="span" key={index} sx={{ color: span.color, fontWeight: span.bold ? 700 : 400 }}>{span.text}</Box>)}</Box>}
  </Paper>;
}

export function ActivityFeed({ events, nodes, workingFolder, live, command = false, hasMore = false, onMore }: {
  events: RunEvent[]; nodes?: RunNode[]; workingFolder?: string; live: boolean;
  command?: boolean; hasMore?: boolean; onMore?: () => Promise<void>;
}) {
  const [scope, setScope] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);
  const [follow, setFollow] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const following = useRef(true);
  const previousRevision = useRef("");
  const root = useRef<HTMLDivElement>(null);
  const tail = useRef<HTMLDivElement>(null);
  const filteredEvents = useMemo(() => scope ? events.filter((event) => event.payload.scope_path === scope) : events, [events, scope]);
  const messages = useMemo(() => activityRows(filteredEvents), [filteredEvents]);
  const rows = messages.filter((message) => relativeActivityText(`${message.text}\n${message.tool?.title ?? ""}`, workingFolder).toLowerCase().includes(search.toLowerCase()));
  const terminal = useMemo(() => {
    const style: AnsiStyle = { bold: false };
    return commandLines(filteredEvents).map((line) => ({ ...line, spans: ansiSpans(relativeActivityText(line.text, workingFolder), style) }));
  }, [filteredEvents, workingFolder]);
  const lines = terminal.filter((line) => `${line.stream} ${line.spans.map((span) => span.text).join("")}`.toLowerCase().includes(search.toLowerCase()));
  const count = command ? lines.length : rows.length;
  const revision = `${events.at(-1)?.id ?? 0}:${events.length}:${messages.at(-1)?.lastId ?? 0}`;
  function followingLatest(value: boolean): void { following.current = value; setFollow(value); }
  function jump(): void { followingLatest(true); tail.current?.scrollIntoView({ block: "end" }); }
  useEffect(() => {
    let scrollPosition = window.scrollY;
    const scroll = () => {
      if (window.scrollY < scrollPosition - 2) { following.current = false; setFollow(false); }
      scrollPosition = window.scrollY;
    };
    window.addEventListener("scroll", scroll, { passive: true });
    return () => window.removeEventListener("scroll", scroll);
  }, []);
  useEffect(() => {
    const previous = previousRevision.current;
    previousRevision.current = revision;
    if (!previous || previous === revision || !live || !following.current) return;
    const bounds = root.current?.getBoundingClientRect();
    // Follow only while the owner is reading this feed. Opening a run must
    // keep its header and actionable requests in view.
    if (bounds && bounds.top < window.innerHeight && bounds.bottom > 0) tail.current?.scrollIntoView({ block: "end" });
  }, [revision, live]);
  async function more(): Promise<void> {
    followingLatest(false);
    setLoading(true);
    setError(null);
    try {
      if (count <= limit && onMore) await onMore();
      setLimit((current) => current + 100);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setLoading(false); }
  }
  return <Stack ref={root} spacing={1.5} component="section" aria-label="Activity feed">
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: { sm: "center" } }}>
      {nodes && <FormControl size="small" sx={{ minWidth: 180 }}><InputLabel id="activity-job-filter">Filter by job</InputLabel>
        <Select labelId="activity-job-filter" label="Filter by job" value={scope} onChange={(event) => { setScope(event.target.value); followingLatest(false); setLimit(100); }}>
          <MenuItem value="">All jobs</MenuItem>{nodes.map((node) => <MenuItem key={node.scope_path} value={node.scope_path}>{stageLabel(node.scope_path)}</MenuItem>)}
        </Select></FormControl>}
      <TextField label="Search activity" size="small" value={search} onChange={(event) => { setSearch(event.target.value); followingLatest(false); setLimit(100); }} />
      <FormControlLabel control={<Switch checked={follow} onChange={(event) => event.target.checked ? jump() : followingLatest(false)} />} label="Follow latest" />
      {!follow && count > 0 && <Button onClick={jump}>Jump to latest</Button>}
    </Stack>
    {error && <Alert severity="error">{error}</Alert>}
    {(count > limit || hasMore) && <Button disabled={loading} onClick={() => void more()}>{loading ? "Loading messages…" : "Load earlier messages"}</Button>}
    {command ? <Box component="ol" aria-label="Command output lines" start={Math.max(1, lines.length - limit + 1)} sx={{ bgcolor: "var(--relay-terminal)", color: "var(--relay-text-on-dark)", fontFamily: "monospace", p: 2, pl: 7, m: 0 }}>
      {lines.slice(-limit).map((line, index) => <Box component="li" key={index} sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", pl: 1 }}>
        <Box component="span" sx={{ color: line.stream === "stderr" ? "var(--relay-danger-on-dark)" : "var(--relay-muted-on-dark)", mr: 1 }}>{line.stream}</Box>
        {line.spans.map((span, part) => <Box component="span" key={part} sx={{ color: span.color, fontWeight: span.bold ? 700 : 400 }}>{span.text}</Box>)}
      </Box>)}
    </Box> : <Stack spacing={1.5}>{rows.slice(-limit).map((message) => <ActivityMessageView key={message.id} message={message} workingFolder={workingFolder} />)}</Stack>}
    {count === 0 && <Typography color="text.secondary">{search || scope ? "No messages match these filters." : "Messages will appear here when this job starts."}</Typography>}
    <Box ref={tail} aria-hidden />
  </Stack>;
}
