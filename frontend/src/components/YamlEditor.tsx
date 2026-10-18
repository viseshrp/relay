import { yaml } from "@codemirror/lang-yaml";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView, hoverTooltip, keymap } from "@codemirror/view";
import { autocompletion } from "@codemirror/autocomplete";
import { indentWithTab } from "@codemirror/commands";
import { indentUnit } from "@codemirror/language";
import { lintGutter, setDiagnostics } from "@codemirror/lint";
import { basicSetup } from "codemirror";
import { useTheme } from "@mui/material/styles";
import { useEffect, useRef } from "react";
import { createCodeMirrorTheme } from "../theme";
import type { LanguageManifest } from "../workflow-language";
import { completionsAt, hoverTextAt } from "../yaml-completion";

type EditorDiagnostic = {
  message: string;
  context?: { line?: string; column?: string };
};

interface YamlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  manifest?: LanguageManifest | null;
  diagnostics?: EditorDiagnostic[];
  /** Non-blocking findings, marked as warnings rather than errors. */
  warnings?: EditorDiagnostic[];
  /** Agent IDs offered for an agent step's agent input. */
  agentIds?: string[];
}

const NONE: EditorDiagnostic[] = [];

export function YamlEditor({
  value,
  onChange,
  onBlur,
  manifest,
  diagnostics = NONE,
  warnings = NONE,
  agentIds = [],
}: YamlEditorProps) {
  const muiTheme = useTheme();
  const isDark = muiTheme.palette.mode === "dark";
  const isDarkRef = useRef(isDark);
  isDarkRef.current = isDark;
  const themeCompartment = useRef(new Compartment());
  const parent = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changeHandler = useRef(onChange);
  const blurHandler = useRef(onBlur);
  const currentValue = useRef(value);
  currentValue.current = value;
  const applyingExternalValue = useRef(false);
  const schema = useRef(manifest);
  schema.current = manifest;
  const agents = useRef(agentIds);
  agents.current = agentIds;

  changeHandler.current = onChange;
  blurHandler.current = onBlur;

  useEffect(() => {
    if (parent.current === null) return;
    const editor = new EditorView({
      parent: parent.current,
      state: EditorState.create({
        doc: currentValue.current,
        extensions: [
          basicSetup,
          keymap.of([indentWithTab]),
          indentUnit.of("  "),
          themeCompartment.current.of(createCodeMirrorTheme(isDarkRef.current)),
          yaml(),
          lintGutter(),
          autocompletion({
            override: [
              (context) => {
                const manifest = schema.current;
                // Open by itself only once a word is being typed.
                if (
                  !manifest ||
                  (!context.explicit && !context.matchBefore(/[\w./@-]+/))
                )
                  return null;
                const result = completionsAt(
                  context.state.doc.toString(),
                  context.pos,
                  manifest,
                  { agents: agents.current },
                );
                // Options arrive filtered and in the order to show them.
                return result && { ...result, filter: false };
              },
            ],
          }),
          hoverTooltip((editor, position) => {
            const manifest = schema.current;
            const content =
              manifest &&
              hoverTextAt(editor.state.doc.toString(), position, manifest);
            if (!content) return null;
            const line = editor.state.doc.lineAt(position);
            const offset = position - line.from;
            const word = [...line.text.matchAll(/[\w./@-]+/g)].find(
              (item) =>
                item.index <= offset && item.index + item[0].length >= offset,
            );
            return {
              pos: line.from + (word?.index ?? offset),
              end: line.from + (word ? word.index + word[0].length : offset),
              create: () => {
                const dom = document.createElement("div");
                dom.textContent = content;
                dom.className = "yaml-help";
                return { dom };
              },
            };
          }),
          EditorView.contentAttributes.of({ "aria-label": "Workflow YAML" }),
          EditorView.lineWrapping,
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !applyingExternalValue.current) {
              changeHandler.current(update.state.doc.toString());
            }
          }),
          EditorView.domEventHandlers({
            blur: () => {
              blurHandler.current?.();
            },
          }),
          EditorView.theme({
            "&": { height: "100%", fontSize: "13px" },
            ".cm-scroller": {
              overflow: "auto",
              fontFamily: '"JetBrains Mono", monospace',
            },
            ".cm-content": { minHeight: "520px" },
          }),
        ],
      }),
    });
    editor.scrollDOM.tabIndex = 0;
    editor.scrollDOM.setAttribute("aria-label", "Scrollable workflow YAML");
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    editor.dispatch({
      effects: themeCompartment.current.reconfigure(
        createCodeMirrorTheme(isDark),
      ),
    });
  }, [isDark]);

  useEffect(() => {
    const editor = view.current;
    if (editor === null || editor.state.doc.toString() === value) return;
    applyingExternalValue.current = true;
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: value },
    });
    applyingExternalValue.current = false;
  }, [value]);

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    editor.dispatch(
      setDiagnostics(
        editor.state,
        // A diagnostic without a line stays in the banner and underlines nothing.
        [
          ...diagnostics.map((item) => ({ item, severity: "error" as const })),
          ...warnings.map((item) => ({ item, severity: "warning" as const })),
        ].flatMap(({ item, severity }) => {
          if (!Number(item.context?.line)) return [];
          const number = Math.min(
            editor.state.doc.lines,
            Math.max(1, Number(item.context?.line)),
          );
          const line = editor.state.doc.line(number);
          const from = Math.min(
            line.to,
            line.from + Math.max(0, (Number(item.context?.column) || 1) - 1),
          );
          return [
            {
              from,
              to: Math.min(
                line.to,
                from +
                  Math.max(
                    1,
                    line.text.slice(from - line.from).match(/^[\w-]+/)?.[0]
                      .length ?? 1,
                  ),
              ),
              severity,
              message: item.message,
            },
          ];
        }),
      ),
    );
  }, [diagnostics, warnings, value]);

  return (
    <div
      className="yaml-editor"
      ref={parent}
      aria-label="Workflow YAML editor"
    />
  );
}
