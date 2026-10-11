export const WELCOME_SEEN = "relay.welcome-seen";
export const TOUR_SEEN = "relay.tour-seen";

export function hasSeen(key: string): boolean {
  try {
    return localStorage.getItem(key) === "true";
  } catch {
    return false;
  }
}

export function rememberSeen(key: string): void {
  try {
    localStorage.setItem(key, "true");
  } catch {
    /* In restricted browsers, dismissal still lasts for this app session. */
  }
}

export function resetOnboarding(): boolean {
  try {
    localStorage.removeItem(WELCOME_SEEN);
    localStorage.removeItem(TOUR_SEEN);
    return true;
  } catch {
    return false;
  }
}

export type SettingsSection =
  | "Global defaults"
  | "Project defaults"
  | "Server and account"
  | "Notifications"
  | "Storage"
  | "Welcome and guided tour";
