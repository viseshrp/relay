import { Props } from "./DefaultSettingsFormShared";
import { useDefaultSettingsForm } from "./useDefaultSettingsForm";
import { DefaultSettingsFormView } from "./DefaultSettingsFormView";
export function DefaultSettingsForm(props: Props) {
  const state = useDefaultSettingsForm(props);
  if (state.fallback !== null) return state.fallback;
  return <DefaultSettingsFormView state={state} />;
}
