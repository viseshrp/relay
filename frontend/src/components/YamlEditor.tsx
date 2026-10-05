import { yaml } from "@codemirror/lang-yaml";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

interface YamlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
}

export function YamlEditor({ value, onChange, onBlur }: YamlEditorProps) {
  const parent = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changeHandler = useRef(onChange);
  const blurHandler = useRef(onBlur);
  const applyingExternalValue = useRef(false);

  changeHandler.current = onChange;
  blurHandler.current = onBlur;

  useEffect(() => {
    if (parent.current === null) return;
    const editor = new EditorView({
      parent: parent.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          yaml(),
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
            ".cm-scroller": { overflow: "auto", fontFamily: "ui-monospace, monospace" },
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
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    applyingExternalValue.current = false;
  }, [value]);

  return <div className="yaml-editor" ref={parent} aria-label="Workflow YAML editor" />;
}
