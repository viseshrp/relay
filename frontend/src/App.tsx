import { useApp } from "./useApp";
import { AppView } from "./AppView";
export function App() {
  const state = useApp();
  if (state.fallback !== null) return state.fallback;
  return <AppView state={state} />;
}
