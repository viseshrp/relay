import { Props } from "./SettingsPageShared";
import { useSettingsPage } from "./useSettingsPage";
import { SettingsPageView } from "./SettingsPageView";
export function SettingsPage(props: Props) {
  const state = useSettingsPage(props);
  if (state.fallback !== null) return state.fallback;
  return <SettingsPageView state={state} />;
}
