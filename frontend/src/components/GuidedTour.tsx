import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { useEffect } from "react";
import { help, type HelpTopic } from "../help";
import { rememberSeen, TOUR_SEEN, type SettingsSection } from "../onboarding";

export interface TourDestination {
  section?: SettingsSection;
}
const steps: {
  topic: HelpTopic;
  target?: string;
  section?: SettingsSection;
}[] = [
  { topic: "project" },
  { topic: "workflows", target: "workflow-tab" },
  { topic: "runs", target: "runs-tab" },
  ...(
    [
      "agentOrder",
      "sharedModel",
      "providers",
      "effort",
      "permissions",
      "commands",
      "environment",
      "timeout",
      "autoRetry",
      "recovery",
      "retryLimit",
      "cleanup",
      "repairs",
      "repairRounds",
      "fixer",
      "verifier",
    ] as const
  ).map((topic) => ({
    topic,
    section: "Global defaults" as const,
    target: topic === "effort" || topic === "permissions" ? "providers" : topic,
  })),
  {
    topic: "override",
    target: "settings-navigation",
    section: "Project defaults",
  },
  { topic: "login", section: "Server and account" },
  { topic: "host", section: "Server and account" },
  { topic: "port", section: "Server and account" },
  { topic: "workers", section: "Server and account" },
  { topic: "notifications", section: "Notifications" },
  { topic: "storage", section: "Storage" },
  { topic: "onboarding", section: "Welcome and guided tour" },
];

export function GuidedTour({
  onDestination,
  onClose,
}: {
  onDestination: (destination: TourDestination) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    let disposing = false;
    let closed = false;
    function finish(): void {
      if (disposing || closed) return;
      closed = true;
      onClose();
    }
    rememberSeen(TOUR_SEEN);
    const definitions: DriveStep[] = steps.map(({ topic, target }) => ({
      element: `[data-tour="${target ?? topic}"]`,
      waitForElement: 5000,
      popover: { title: help[topic][0], description: help[topic][1] },
    }));
    const tour = driver({
      steps: definitions,
      animate: false,
      smoothScroll: false,
      showProgress: true,
      progressText: "{{current}} of {{total}}",
      nextBtnText: "Next",
      prevBtnText: "Back",
      doneBtnText: "Finish",
      closeBtnLabel: "Skip tour",
      overlayClickBehavior: "none",
      disableActiveInteraction: true,
      stagePadding: 8,
      stageRadius: 8,
      popoverClass: "relay-tour",
      overlayOpacity: 0.6,
      onHighlighted: (element) => {
        // Driver adds disclosure state to every target, including plain layout
        // containers. Only interactive targets support aria-expanded.
        if (
          element &&
          !element.matches(
            'button, a, input, select, [role="button"], [role="combobox"], [role="link"], [role="treeitem"]',
          )
        )
          element.removeAttribute("aria-expanded");
      },
      onPopoverRender: (popover) => {
        // Keep the skip action visible, including for keyboard and touch users.
        popover.closeButton.textContent = "Skip";
        popover.closeButton.setAttribute("aria-label", "Skip tour");
        popover.wrapper.setAttribute("aria-modal", "true");
        popover.nextButton.focus();
      },
      onNextClick: () => move((tour.getActiveIndex() ?? 0) + 1),
      onPrevClick: () => move((tour.getActiveIndex() ?? 0) - 1),
      onDoneClick: () => {
        tour.destroy();
        finish();
      },
      // Driver can close before its highlight has finished initializing.
      // Its onDestroyed hook only runs when an active element exists.
      onDestroyStarted: () => {
        tour.destroy();
        finish();
      },
      onDestroyed: finish,
    });
    function move(index: number): void {
      const step = steps[index];
      if (!step) return;
      onDestination({ section: step.section });
      tour.moveTo(index);
    }
    // Tour keyboard focus belongs to its controls, never to editable settings.
    const keepFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const controls = Array.from(
        document.querySelectorAll<HTMLButtonElement>(
          ".relay-tour button:not(:disabled)",
        ),
      ).filter((button) => button.offsetParent !== null);
      if (!controls.length) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const position = controls.findIndex(
        (button) => button === document.activeElement,
      );
      const next =
        (position + (event.shiftKey ? -1 : 1) + controls.length) %
        controls.length;
      controls[next]?.focus();
    };
    document.addEventListener("keydown", keepFocus, true);
    tour.drive();
    return () => {
      disposing = true;
      document.removeEventListener("keydown", keepFocus, true);
      tour.destroy();
    };
  }, [onClose, onDestination]);
  return null;
}
