import { GetStartedProps } from "./GetStartedShared";
import { useGetStarted } from "./useGetStarted";
import { GetStartedView } from "./GetStartedView";
export function GetStarted(props: GetStartedProps) {
  const state = useGetStarted(props);
  if (state.fallback !== null) return state.fallback;
  return <GetStartedView state={state} />;
}
