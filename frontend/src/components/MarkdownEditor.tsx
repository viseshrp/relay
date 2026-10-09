import { markdown } from "@codemirror/lang-markdown";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { Button, Stack } from "@mui/material";
import { useEffect, useRef, useState } from "react";
import { SafeMarkdown } from "./SafeMarkdown";

export function MarkdownEditor({ label, value, readonly = false, onChange }: { label: string; value: string; readonly?: boolean; onChange: (value: string) => void }) {
  const parent = useRef<HTMLDivElement>(null); const view = useRef<EditorView | null>(null);
  const callback = useRef(onChange); callback.current = onChange;
  const applying = useRef(false); const [preview, setPreview] = useState(false);
  useEffect(() => {
    if (!parent.current || preview) return;
    const editor = new EditorView({ parent: parent.current, state: EditorState.create({ doc: value, extensions: [basicSetup, markdown(), EditorView.lineWrapping,
      EditorView.contentAttributes.of({ "aria-label": label }), EditorState.readOnly.of(readonly), EditorView.editable.of(!readonly),
      EditorView.theme({ ".cm-content": { minHeight: "160px" }, "&": { fontSize: "14px" }, ".cm-scroller": { fontFamily: "ui-monospace, monospace" } }),
      EditorView.updateListener.of(update => { if (update.docChanged && !applying.current) callback.current(update.state.doc.toString()); }),
    ] }) });
    view.current = editor;
    return () => { editor.destroy(); view.current = null; };
  }, [label, readonly, preview]);
  useEffect(() => {
    const editor = view.current;
    if (!editor || editor.state.doc.toString() === value) return;
    applying.current = true; editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } }); applying.current = false;
  }, [value]);
  return <Stack spacing={1}>
    <Button aria-pressed={preview} sx={{ alignSelf: "start" }} onClick={() => setPreview(!preview)}>{preview ? "Edit Markdown" : "Preview Markdown"}</Button>
    {preview ? <div className="markdown-preview"><SafeMarkdown text={value} /></div> : <div className="markdown-editor" ref={parent} />}
  </Stack>;
}
