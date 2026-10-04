import {
  Alert, Button, Checkbox, Dialog, DialogContent, DialogTitle,
  FormControlLabel, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { Fragment, useId, useMemo, useState } from "react";

import { parseGitDiff, splitDiffLines, type DiffFile, type DiffLine } from "../diff";

function fileName(file: DiffFile) { return file.status === "Deleted" ? file.before : file.after; }
function Counts({ added, removed }: { added: number; removed: number }) {
  return <span className="diff-counts" aria-label={`${added} ${added === 1 ? "line" : "lines"} added, ${removed} ${removed === 1 ? "line" : "lines"} removed`}>
    <span className="diff-add-count">+{added}</span><span className="diff-remove-count">−{removed}</span>
  </span>;
}
function LineText({ line }: { line: DiffLine | null }) {
  return line && <><span className="diff-code-text">{line.text || "\u00a0"}</span>
    {line.noNewline && <span className="diff-newline-note">No newline at end of file</span>}
  </>;
}
function FilePatch({ file, split }: { file: DiffFile; split: boolean }) {
  const hunks = useMemo(() => file.hunks.map((hunk) => ({ ...hunk, rows: split ? splitDiffLines(hunk.lines) : [] })), [file, split]);
  if (file.binary) return <p className="diff-empty">Binary file. A text comparison is unavailable.</p>;
  if (file.hunks.length === 0) return <p className="diff-empty">{file.status === "Renamed" ? "File renamed. No text changes in this preview." : "No text changes in this preview."}</p>;
  return <table className={`diff-table ${split ? "diff-table-split" : "diff-table-inline"}`} aria-label={`Changes in ${fileName(file)}`}>
    <colgroup>{split ? <><col className="diff-number-col" /><col className="diff-code-col" /><col className="diff-number-col" /><col className="diff-code-col" /></> : <><col className="diff-number-col" /><col className="diff-number-col" /><col className="diff-marker-col" /><col /></>}</colgroup>
    <thead><tr>{split ? <><th colSpan={2} scope="colgroup">Before</th><th colSpan={2} scope="colgroup">After</th></> : <><th scope="col">Before</th><th scope="col">After</th><th colSpan={2} scope="colgroup">Changes</th></>}</tr></thead>
    <tbody>{hunks.map((hunk, index) => <Fragment key={index}>
      <tr className="diff-hunk"><td colSpan={4}>{hunk.heading}</td></tr>
      {split ? hunk.rows.map((row, offset) => <tr key={offset}>
        <td className={`diff-number diff-${row.before?.kind ?? "empty"}`}>{row.before?.before}</td>
        <td className={`diff-code diff-${row.before?.kind ?? "empty"}`}><span className="diff-sr-label">{row.before?.kind === "removed" ? "Removed: " : ""}</span><LineText line={row.before} /></td>
        <td className={`diff-number diff-${row.after?.kind ?? "empty"}`}>{row.after?.after}</td>
        <td className={`diff-code diff-${row.after?.kind ?? "empty"}`}><span className="diff-sr-label">{row.after?.kind === "added" ? "Added: " : ""}</span><LineText line={row.after} /></td>
      </tr>) : hunk.lines.map((line, offset) => <tr key={offset} className={`diff-${line.kind}`}>
        <td className="diff-number">{line.before}</td><td className="diff-number">{line.after}</td>
        <td className="diff-marker" aria-label={line.kind === "context" ? "Unchanged" : line.kind === "added" ? "Added" : "Removed"}>{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : ""}</td>
        <td className="diff-code"><LineText line={line} /></td>
      </tr>)}
    </Fragment>)}</tbody>
  </table>;
}

export function DiffViewer({ text, truncated }: { text: string; truncated: boolean }) {
  const files = useMemo(() => parseGitDiff(text), [text]);
  const [selected, setSelected] = useState(0);
  const [layout, setLayout] = useState<"inline" | "split">("inline");
  const [wrap, setWrap] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [raw, setRaw] = useState(false);
  const titleId = useId();
  const selectedIndex = Math.min(selected, Math.max(0, files.length - 1));
  const file = files[selectedIndex];
  const totals = useMemo(() => files.reduce((sum, item) => ({ added: sum.added + item.additions, removed: sum.removed + item.removals }), { added: 0, removed: 0 }), [files]);
  if (!text.trim()) return <Typography>No committed code changes yet.</Typography>;
  const content = <div className={`diff-viewer ${expanded ? "diff-expanded" : ""}`}>
    <div className="diff-toolbar">
      <div className="diff-summary"><strong>{files.length} {files.length === 1 ? "changed file" : "changed files"}{truncated ? " in preview" : ""}</strong><Counts added={totals.added} removed={totals.removed} /></div>
      <div className="diff-controls">
        <ToggleButtonGroup size="small" exclusive value={layout} aria-label="Diff layout" onChange={(_event, value: "inline" | "split" | null) => { if (value) setLayout(value); }}>
          <ToggleButton value="inline">Inline</ToggleButton><ToggleButton value="split">Side by side</ToggleButton>
        </ToggleButtonGroup>
        <FormControlLabel className="diff-wrap-toggle" label="Wrap lines" control={<Checkbox size="small" checked={wrap} onChange={(event) => setWrap(event.target.checked)} />} />
        <Button size="small" variant="outlined" onClick={() => setExpanded(!expanded)}>{expanded ? "Close full screen" : "Full screen"}</Button>
      </div>
    </div>
    <p className="diff-legend"><span>− Removed</span><span>+ Added</span><span>Line numbers show before and after.</span></p>
    {truncated && <Alert severity="warning">This is a partial preview. Counts cover only the displayed changes. Review the full diff on the run branch in Advanced diagnostics before responding.</Alert>}
    {!file ? <Alert severity="info">This patch cannot be formatted. Its original text is available below.</Alert> : <div className="diff-browser">
      <nav className="diff-file-list" aria-label="Changed files">
        {files.map((item, index) => <button key={index} type="button" aria-current={index === selectedIndex ? "true" : undefined} className={`diff-file-button ${index === selectedIndex ? "diff-file-selected" : ""}`} onClick={() => { setSelected(index); }}>
          <span className="diff-file-name">{fileName(item)}</span>
          <span className="diff-file-meta"><span>{item.binary ? "Binary" : item.status}</span><Counts added={item.additions} removed={item.removals} /></span>
        </button>)}
      </nav>
      <section className="diff-file-panel" aria-label={`File ${fileName(file)}`} key={selectedIndex}>
        <div className="diff-file-heading"><strong>{fileName(file)}</strong><Counts added={file.additions} removed={file.removals} /></div>
        {(file.status === "Renamed" || file.status === "Copied") && <p className="diff-file-origin">{file.status} from {file.before}</p>}
        <div className={`diff-scroll ${wrap ? "diff-wrap" : ""}`} tabIndex={0} role="region" aria-label={`Scrollable changes in ${fileName(file)}`}><FilePatch file={file} split={layout === "split"} /></div>
        <details className="diff-file-details"><summary>File details</summary><pre>{file.metadata.join("\n")}</pre></details>
      </section>
    </div>}
    <Button size="small" onClick={() => setRaw(!raw)} aria-expanded={raw}>{raw ? "Hide original patch" : "Show original patch"}</Button>
    {(raw || !file) && <pre className="diff-original">{text}</pre>}
  </div>;
  return expanded ? <Dialog fullScreen open onClose={() => setExpanded(false)} aria-labelledby={titleId}>
    <DialogTitle id={titleId}>Committed code changes</DialogTitle><DialogContent>{content}</DialogContent>
  </Dialog> : content;
}
