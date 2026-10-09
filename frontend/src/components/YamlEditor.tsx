import { yaml } from "@codemirror/lang-yaml";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { hoverTooltip } from "@codemirror/view";
import { autocompletion } from "@codemirror/autocomplete";
import { lintGutter, setDiagnostics } from "@codemirror/lint";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";
import type { LanguageManifest } from "../workflow-language";

interface YamlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  manifest?: LanguageManifest | null;
  diagnostics?: Array<{
    message: string;
    context?: { line?: string; column?: string };
  }>;
}

export function YamlEditor({
  value,
  onChange,
  onBlur,
  manifest,
  diagnostics = [],
}: YamlEditorProps) {
  const parent = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changeHandler = useRef(onChange);
  const blurHandler = useRef(onBlur);
  const currentValue = useRef(value);
  currentValue.current = value;
  const applyingExternalValue = useRef(false);
  const schema = useRef(manifest);
  schema.current = manifest;

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
          yaml(),
          lintGutter(),
          autocompletion({
            override: [
              (context) => {
                const token = context.matchBefore(/[\w.-]*/);
                if (!token || (!token.text && !context.explicit)) return null;
                const definitions = schema.current?.definitions ?? {};
                const fields = new Map<string, string>();
                for (const definition of Object.values(definitions))
                  for (const [key, descriptor] of Object.entries(
                    definition.mapping?.properties ?? {},
                  )) {
                    const type =
                      typeof descriptor === "string"
                        ? descriptor
                        : descriptor.type;
                    fields.set(
                      key,
                      definitions[type]?.description ??
                        definition.description ??
                        "Relay workflow field",
                    );
                  }
                for (const fieldsForAction of Object.values(
                  schema.current?.builtin_inputs ?? {},
                ))
                  for (const key of fieldsForAction.allowed)
                    fields.set(key, "Local action input");
                for (const [name, properties] of Object.entries(
                  schema.current?.context_properties ?? {},
                ))
                  for (const key of properties)
                    fields.set(`${name}.${key}`, "Expression context");
                return {
                  from: token.from,
                  options: [...fields].map(([label, info]) => ({
                    label,
                    type: "property",
                    info,
                  })),
                };
              },
            ],
          }),
          hoverTooltip((editor, position) => {
            const line = editor.state.doc.lineAt(position);
            const offset = position - line.from;
            const match = [...line.text.matchAll(/[\w-]+/g)].find(
              (item) =>
                item.index <= offset && item.index + item[0].length >= offset,
            );
            if (!match) return null;
            for (const definition of Object.values(
              schema.current?.definitions ?? {},
            )) {
              const descriptor = definition.mapping?.properties?.[match[0]];
              if (!descriptor) continue;
              const type =
                typeof descriptor === "string" ? descriptor : descriptor.type;
              const content =
                schema.current?.definitions[type]?.description ??
                definition.description ??
                `${match[0]}: ${type}`;
              return {
                pos: line.from + match.index,
                end: line.from + match.index + match[0].length,
                create: () => {
                  const dom = document.createElement("div");
                  dom.textContent = content;
                  dom.className = "yaml-help";
                  return { dom };
                },
              };
            }
            return null;
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
              fontFamily: "ui-monospace, monospace",
            },
            ".cm-content": { minHeight: "520px" },
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, []);

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
        diagnostics.map((item) => {
          const number = Math.min(
            editor.state.doc.lines,
            Math.max(1, Number(item.context?.line) || 1),
          );
          const line = editor.state.doc.line(number);
          const from = Math.min(
            line.to,
            line.from + Math.max(0, (Number(item.context?.column) || 1) - 1),
          );
          return {
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
            severity: "error" as const,
            message: item.message,
          };
        }),
      ),
    );
  }, [diagnostics, value]);

  return (
    <div
      className="yaml-editor"
      ref={parent}
      aria-label="Workflow YAML editor"
    />
  );
}
