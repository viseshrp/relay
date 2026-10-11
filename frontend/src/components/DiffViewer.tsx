import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { parseGitDiff, type DiffFile } from "../diff";

// Load the highlighter only when a review contains text changes.
const HighlightedDiff = lazy(() => import("./HighlightedDiff"));

class DiffRenderBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    console.error("Unable to display the code comparison", error);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function fileName(file: DiffFile) {
  return file.status === "Deleted" ? file.before : file.after;
}
function Counts({ added, removed }: { added: number; removed: number }) {
  return (
    <span
      className="diff-counts"
      aria-label={`${added} ${added === 1 ? "line" : "lines"} added, ${removed} ${removed === 1 ? "line" : "lines"} removed`}
    >
      <span className="diff-add-count">+{added}</span>
      <span className="diff-remove-count">−{removed}</span>
    </span>
  );
}
function FilePatch({
  file,
  split,
  wrap,
}: {
  file: DiffFile;
  split: boolean;
  wrap: boolean;
}) {
  if (file.binary)
    return (
      <p className="diff-empty">
        Binary file. A text comparison is unavailable.
      </p>
    );
  if (!file.hasHunks)
    return (
      <p className="diff-empty">
        {file.status === "Renamed"
          ? "File renamed. No text changes in this preview."
          : "No text changes in this preview."}
      </p>
    );
  const fallback = (
    <>
      <Alert severity="info">
        This comparison could not be displayed. Review the original patch below.
      </Alert>
      <pre className="diff-original">{file.patch}</pre>
    </>
  );
  return (
    <DiffRenderBoundary fallback={fallback}>
      <Suspense
        fallback={
          <p className="diff-empty" role="status">
            Loading code comparison…
          </p>
        }
      >
        {split &&
          (file.status === "Added" || file.status === "Deleted" ? (
            // New and deleted files have only one side in the rendered comparison.
            <div className="diff-column-labels diff-column-single">
              <span>{file.status === "Added" ? "After" : "Before"}</span>
            </div>
          ) : (
            <div className="diff-column-labels">
              <span>Before</span>
              <span>After</span>
            </div>
          ))}
        <HighlightedDiff
          patch={file.patch}
          split={split}
          wrap={wrap}
          fallback={fallback}
        />
      </Suspense>
    </DiffRenderBoundary>
  );
}

export function DiffViewer({
  text,
  truncated,
}: {
  text: string;
  truncated: boolean;
}) {
  const files = useMemo(() => parseGitDiff(text), [text]);
  const [selected, setSelected] = useState(0);
  const [layout, setLayout] = useState<"inline" | "split">("inline");
  const [wrap, setWrap] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [raw, setRaw] = useState(false);
  const expandButton = useRef<HTMLButtonElement>(null);
  const wasExpanded = useRef(false);
  useEffect(() => {
    // The inline button is replaced by the dialog, so focus its replacement on close.
    if (!expanded && wasExpanded.current) expandButton.current?.focus();
    wasExpanded.current = expanded;
  }, [expanded]);
  const titleId = useId();
  const selectedIndex = Math.min(selected, Math.max(0, files.length - 1));
  const file = files[selectedIndex];
  const totals = useMemo(
    () =>
      files.reduce(
        (sum, item) => ({
          added: sum.added + item.additions,
          removed: sum.removed + item.removals,
        }),
        { added: 0, removed: 0 },
      ),
    [files],
  );
  if (!text.trim())
    return <Typography>No committed code changes yet.</Typography>;
  const content = (
    <div className={`diff-viewer ${expanded ? "diff-expanded" : ""}`}>
      <div className="diff-toolbar">
        <div className="diff-summary">
          <strong>
            {files.length}{" "}
            {files.length === 1 ? "changed file" : "changed files"}
            {truncated ? " in preview" : ""}
          </strong>
          <Counts added={totals.added} removed={totals.removed} />
        </div>
        <div className="diff-controls">
          <ToggleButtonGroup
            size="small"
            exclusive
            value={layout}
            aria-label="Diff layout"
            onChange={(_event, value: "inline" | "split" | null) => {
              if (value) setLayout(value);
            }}
          >
            <ToggleButton value="inline">Inline</ToggleButton>
            <ToggleButton value="split">Side by side</ToggleButton>
          </ToggleButtonGroup>
          <FormControlLabel
            className="diff-wrap-toggle"
            label="Wrap lines"
            control={
              <Checkbox
                size="small"
                checked={wrap}
                onChange={(event) => setWrap(event.target.checked)}
              />
            }
          />
          <Button
            ref={expandButton}
            size="small"
            variant="outlined"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Close full screen" : "Full screen"}
          </Button>
        </div>
      </div>
      <p className="diff-legend">
        <span>− Removed</span>
        <span>+ Added</span>
        <span>Line numbers show before and after.</span>
      </p>
      {truncated && (
        <Alert severity="warning">
          This is a partial preview. Counts cover only the displayed changes.
          Review the full diff on the run branch in Advanced diagnostics before
          responding.
        </Alert>
      )}
      {!file ? (
        <Alert severity="info">
          This patch cannot be formatted. Its original text is available below.
        </Alert>
      ) : (
        <div className="diff-browser">
          <nav className="diff-file-list" aria-label="Changed files">
            {files.map((item, index) => (
              <button
                key={index}
                type="button"
                aria-current={index === selectedIndex ? "true" : undefined}
                className={`diff-file-button ${index === selectedIndex ? "diff-file-selected" : ""}`}
                onClick={() => {
                  setSelected(index);
                }}
              >
                <span className="diff-file-name">{fileName(item)}</span>
                <span className="diff-file-meta">
                  <span>{item.binary ? "Binary" : item.status}</span>
                  <Counts added={item.additions} removed={item.removals} />
                </span>
              </button>
            ))}
          </nav>
          <section
            className="diff-file-panel"
            aria-label={`File ${fileName(file)}`}
            key={selectedIndex}
          >
            <div className="diff-file-heading">
              <strong>{fileName(file)}</strong>
              <Counts added={file.additions} removed={file.removals} />
            </div>
            {(file.status === "Renamed" || file.status === "Copied") && (
              <p className="diff-file-origin">
                {file.status} from {file.before}
              </p>
            )}
            <div
              className="diff-scroll"
              tabIndex={0}
              role="region"
              aria-label={`Scrollable changes in ${fileName(file)}`}
            >
              <FilePatch file={file} split={layout === "split"} wrap={wrap} />
            </div>
            <details className="diff-file-details">
              <summary>File details</summary>
              <pre>{file.metadata.join("\n")}</pre>
            </details>
          </section>
        </div>
      )}
      <Button size="small" onClick={() => setRaw(!raw)} aria-expanded={raw}>
        {raw ? "Hide original patch" : "Show original patch"}
      </Button>
      {(raw || !file) && <pre className="diff-original">{text}</pre>}
    </div>
  );
  return expanded ? (
    <Dialog
      fullScreen
      open
      onClose={() => setExpanded(false)}
      aria-labelledby={titleId}
    >
      <DialogTitle id={titleId}>Committed code changes</DialogTitle>
      <DialogContent>{content}</DialogContent>
    </Dialog>
  ) : (
    content
  );
}
