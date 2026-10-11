import { StreamLanguage } from "@codemirror/language";
import { shell as shellMode } from "@codemirror/legacy-modes/mode/shell";
import { python } from "@codemirror/legacy-modes/mode/python";
import { powerShell } from "@codemirror/legacy-modes/mode/powershell";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { Box, Typography } from "@mui/material";
import { useEffect, useRef } from "react";
import type { LanguageManifest } from "../workflow-language";

export function ScriptEditor({
  value,
  shell,
  manifest,
  onChange,
}: {
  value: string;
  shell?: string;
  manifest: LanguageManifest;
  onChange: (value: string) => void;
}) {
  const parent = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const currentValue = useRef(value);
  currentValue.current = value;
  const callback = useRef(onChange);
  callback.current = onChange;
  const applying = useRef(false);
  const plan = manifest.host_scripts?.[shell || "default"];
  const language = plan?.shell ?? shell ?? "bash";
  useEffect(() => {
    if (!parent.current) return;
    const editor = new EditorView({
      parent: parent.current,
      state: EditorState.create({
        doc: currentValue.current,
        extensions: [
          basicSetup,
          StreamLanguage.define(
            language === "python"
              ? python
              : ["pwsh", "powershell"].includes(language)
                ? powerShell
                : shellMode,
          ),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ "aria-label": "Script" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !applying.current)
              callback.current(update.state.doc.toString());
          }),
          EditorView.theme({
            ".cm-content": { minHeight: "120px" },
            "&": { fontSize: "14px" },
          }),
        ],
      }),
    });
    editor.scrollDOM.tabIndex = 0;
    editor.scrollDOM.setAttribute("aria-label", "Scrollable script");
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, [language]);
  useEffect(() => {
    const editor = view.current;
    if (!editor || editor.state.doc.toString() === value) return;
    applying.current = true;
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: value },
    });
    applying.current = false;
  }, [value]);
  return (
    <Box>
      <Typography component="label">Script</Typography>
      <div className="script-editor" ref={parent} />
      {plan && (
        <Box component="details">
          <Box component="summary">Process arguments</Box>
          <Box
            component="pre"
            sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
          >
            {JSON.stringify(plan.argv, null, 2)}
          </Box>
          <Typography variant="body2">
            Relay replaces &lt;private attempt&gt; with the job's private
            directory when it starts. Arguments come from the same planner used
            to execute the script.
          </Typography>
          {!plan.installed && (
            <Typography color="error">
              This shell is not installed on the Relay host.
            </Typography>
          )}
        </Box>
      )}
    </Box>
  );
}
