import type { ProjectRecord } from "../types";

import type { SettingsSection } from "../onboarding";
const sections = [
  "Global defaults",
  "Project defaults",
  "Server and account",
  "Notifications",
  "Storage",
  "Welcome and guided tour",
] as const;
type Section = (typeof sections)[number];
interface Props {
  project: ProjectRecord | undefined;
  requestProject: string | null;
  notifications: boolean;
  onToggleNotifications: () => Promise<void>;
  tourSection?: SettingsSection | null;
  onShowWelcome: () => void;
  onShowTour: () => void;
  onResetOnboarding: () => boolean;
  onNavigationReady: (callback: (() => Promise<void>) | null) => void;
}
export { sections, type Section, type Props };
