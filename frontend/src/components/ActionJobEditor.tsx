import {
  useActionJobEditor,
  type ActionJobEditorProps,
} from "./useActionJobEditor";
import { ActionJobEditorView } from "./ActionJobEditorView";
export function ActionJobEditor(props: ActionJobEditorProps) {
  const state = useActionJobEditor(props);
  if (!state) return null;
  if (state.fallback !== null) return state.fallback;
  return <ActionJobEditorView state={state} />;
}
