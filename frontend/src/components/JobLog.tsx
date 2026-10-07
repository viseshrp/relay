import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Tooltip, Typography } from "@mui/material";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { errorMessage } from "../api";
import { logMatches, logRows, rawLog } from "../log";
import type { RunEvent } from "../types";
import { ActionIcon } from "./ActionIcon";
import { ActivityMessageView } from "./ActivityFeed";

const ROW_HEIGHT = 26;
function fullscreenShortcut(event: { key: string; shiftKey: boolean; target: EventTarget | null }): boolean {
  return event.key.toLowerCase() === "f" && event.shiftKey
    && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement);
}
function Highlight({ text, ranges, offset }: { text: string; ranges: Array<{ start: number; end: number }>; offset: number }) {
  const parts = [];
  let after = 0;
  for (const range of ranges) {
    const start = Math.max(0, range.start - offset);
    const end = Math.min(text.length, range.end - offset);
    if (end <= start) continue;
    parts.push(<Fragment key={start}>{text.slice(after, start)}<mark>{text.slice(start, end)}</mark></Fragment>);
    after = end;
  }
  return <>{parts}{text.slice(after)}</>;
}
export function JobLog({ events, command, label, workingFolder, live, loading, hasMore, onMore, onRefresh, scope, attempt }: {
  events: RunEvent[]; command: boolean; label: string; workingFolder?: string; live: boolean; loading: boolean;
  hasMore: boolean; onMore: () => Promise<void>; onRefresh: () => void; scope: string; attempt: number | undefined;
}) {
  const rows = useMemo(() => logRows(events, command, workingFolder), [events, command, workingFolder]);
  const [search, setSearch] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const [timestamps, setTimestamps] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [raw, setRaw] = useState(false);
  const [options, setOptions] = useState<HTMLElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [following, setFollowing] = useState(true);
  const follow = useRef(true);
  const viewport = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const previousRevision = useRef("");
  const [viewportHeight, setViewportHeight] = useState(460);
  const [scrollTop, setScrollTop] = useState(0);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setViewportHeight(element.clientHeight));
    observer.observe(element);
    setViewportHeight(element.clientHeight);
    return () => observer.disconnect();
  }, [fullscreen]);
  const matches = useMemo(() => logMatches(rows, search), [rows, search]);
  const current = matches[Math.min(matchIndex, Math.max(0, matches.length - 1))];
  const revision = `${events.at(-1)?.id ?? 0}:${rows.length}:${rows.at(-1)?.text.length ?? 0}`;
  function setFollow(value: boolean) { follow.current = value; setFollowing(value); }
  function jump() { setFollow(true); const element = viewport.current; if (element) { element.scrollTop = element.scrollHeight; setScrollTop(element.scrollTop); } }
  useEffect(() => {
    const previous = previousRevision.current;
    previousRevision.current = revision;
    if (previous && previous !== revision && live && !loading && follow.current) jump();
  }, [revision, live, loading]);
  useEffect(() => {
    if (!current) return;
    const element = viewport.current;
    if (!element) return;
    if (command) { element.scrollTop = Math.max(0, current.row * ROW_HEIGHT - 100); setScrollTop(element.scrollTop); }
    else element.querySelector(`[data-log-row="${current.row}"]`)?.scrollIntoView({ block: "nearest" });
  }, [current?.row, current?.start, command, fullscreen]);
  useEffect(() => {
    const element = root.current;
    const key = (event: KeyboardEvent) => {
      if (fullscreenShortcut(event)) {
        event.preventDefault(); setFullscreen((value) => !value);
      }
    };
    element?.addEventListener("keydown", key);
    return () => element?.removeEventListener("keydown", key);
  }, []);
  function next(direction: number) { if (matches.length) { setFollow(false); setMatchIndex((index) => (index + direction + matches.length) % matches.length); } }
  function download() {
    const url = URL.createObjectURL(new Blob([rawLog(events, command)], { type: "text/plain" }));
    const link = document.createElement("a"); link.href = url;
    link.download = `${scope.replace(/[^a-zA-Z0-9_-]/g, "-")}-attempt-${attempt ?? 0}.log`;
    link.click(); URL.revokeObjectURL(url);
  }
  const start = command ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 12) : 0;
  const end = command ? Math.min(rows.length, start + Math.ceil(viewportHeight / ROW_HEIGHT) + 24) : rows.length;
  const contents = <>
    <Stack className="log-toolbar" direction="row" spacing={1}>
      <TextField size="small" placeholder="Search logs" value={search} slotProps={{ htmlInput: { "aria-label": "Search logs" } }}
        onChange={(event) => { setSearch(event.target.value); setMatchIndex(0); setFollow(false); }}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); next(event.shiftKey ? -1 : 1); } }} />
      {search && <>
        <Typography variant="caption" role="status">{matches.length ? Math.min(matchIndex + 1, matches.length) : 0}/{matches.length}</Typography>
        <IconButton aria-label="Previous match" disabled={!matches.length} onClick={() => next(-1)}><ActionIcon name="up" /></IconButton>
        <IconButton aria-label="Next match" disabled={!matches.length} onClick={() => next(1)}><ActionIcon name="down" /></IconButton>
      </>}
      <Tooltip title="Refresh logs"><IconButton aria-label="Refresh logs" onClick={onRefresh}><ActionIcon name="refresh" /></IconButton></Tooltip>
      <Tooltip title="Log options"><IconButton ref={menuButton} aria-label="Log options" aria-haspopup="menu" aria-expanded={Boolean(options)} onClick={(event) => setOptions(event.currentTarget)}><ActionIcon name="settings" /></IconButton></Tooltip>
      <Menu anchorEl={options} open={Boolean(options)} onClose={() => setOptions(null)}>
        <MenuItem onClick={() => { setTimestamps((value) => !value); setOptions(null); }}>{timestamps ? "Hide timestamps" : "Show timestamps"}</MenuItem>
        <MenuItem onClick={() => { setFullscreen(true); setOptions(null); }}>Show full screen (Shift+F)</MenuItem>
        <MenuItem disabled={loading || hasMore} onClick={() => { download(); setOptions(null); }}>Download logs</MenuItem>
        <MenuItem disabled={loading || hasMore} onClick={() => { setRaw(true); setOptions(null); }}>View raw logs</MenuItem>
        <MenuItem disabled={loading || hasMore} onClick={() => { void navigator.clipboard.writeText(rawLog(events, command)).catch((caught: unknown) => setError(errorMessage(caught))); setOptions(null); }}>Copy output</MenuItem>
      </Menu>
    </Stack>
    {error && <Alert severity="error">{error}</Alert>}
    {hasMore && <Button disabled={loading} onClick={() => void onMore()}>{loading ? "Loading earlier logs…" : "Retry log history"}</Button>}
    <Box ref={viewport} className={`job-log-viewport ${command ? "terminal" : "conversation"}`} tabIndex={0} role="region" aria-label={command ? "Command output lines" : `${label} log`}
      onScroll={(event) => {
        const element = event.currentTarget;
        setScrollTop(element.scrollTop);
        if (element.scrollHeight - element.scrollTop - element.clientHeight > 40) setFollow(false);
      }}>
      {command ? <Box style={{ height: rows.length * ROW_HEIGHT, position: "relative" }}>
        {rows.slice(start, end).map((row, offset) => <div key={row.id} data-log-row={start + offset} className={`terminal-log-row ${current?.row === start + offset ? "active-match" : ""}`} style={{ top: (start + offset) * ROW_HEIGHT }}>
          <span className="log-line-number">{start + offset + 1}</span>
          {timestamps && <time className="log-timestamp">{new Date(row.timestamp).toLocaleTimeString()}</time>}
          <code>{row.spans?.map((span, index, spans) => <span key={index} style={{ color: span.color, fontWeight: span.bold ? 700 : undefined }}><Highlight text={span.text} ranges={matches.filter((match) => match.row === start + offset)} offset={spans.slice(0, index).reduce((total, value) => total + value.text.length, 0)} /></span>)}</code>
        </div>)}
      </Box> : rows.map((row, index) => <Box key={row.id} data-log-row={index} className={`conversation-log-row ${current?.row === index ? "active-match" : ""}`}>
        <span className="log-line-number">{index + 1}</span>
        {row.message && <ActivityMessageView message={row.message} workingFolder={workingFolder} timestamps={timestamps} expanded={current?.row === index} />}
      </Box>)}
      {!rows.length && <Typography sx={{ p: 2 }}>Output will appear here when this job starts.</Typography>}
    </Box>
    <Stack direction="row" className="log-footer" spacing={1}>
      <Typography variant="caption" role="status">{loading ? "Loading log history…" : hasMore ? "Log history incomplete" : live ? "Live logs" : "All logs received"} · {rows.length.toLocaleString()} {command ? "lines" : "messages"}</Typography>
      <Button size="small" onClick={() => following ? setFollow(false) : jump()}>{following ? "Stop following" : "Jump to latest"}</Button>
    </Stack>
  </>;
  return <Box ref={root} className="job-log" tabIndex={-1}>
    {!fullscreen && contents}
    <Dialog open={fullscreen} fullScreen onClose={() => setFullscreen(false)} slotProps={{ transition: { onExited: () => { root.current?.focus(); } } }}>
      <DialogTitle>Job logs <Button onClick={() => setFullscreen(false)} sx={{ float: "right" }}>Exit full screen</Button></DialogTitle>
      <DialogContent className="fullscreen-log" onKeyDown={(event) => { if (fullscreenShortcut(event)) { event.preventDefault(); setFullscreen(false); } }}>{fullscreen && contents}</DialogContent>
    </Dialog>
    <Dialog open={raw} onClose={() => setRaw(false)} fullWidth maxWidth="lg" slotProps={{ transition: { onExited: () => menuButton.current?.focus() } }}>
      <DialogTitle>Raw logs</DialogTitle><DialogContent><Box component="pre" className="activity-text">{rawLog(events, command)}</Box></DialogContent>
      <DialogActions><Button onClick={() => setRaw(false)}>Close</Button><Button onClick={download}>Download logs</Button></DialogActions>
    </Dialog>
  </Box>;
}
