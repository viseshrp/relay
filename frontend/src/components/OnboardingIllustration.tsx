import { highlights } from "../assets/welcome/highlights";

const screens = {
  project: { number: 1, section: "Project", control: "Repository folder", caption: "Choose your local Git repository", image: new URL("../assets/welcome/project.png", import.meta.url).href },
  workflow: { number: 2, section: "Workflows", control: "Build stage", caption: "Select a stage to edit what it does", image: new URL("../assets/welcome/workflow.png", import.meta.url).href },
  run: { number: 3, section: "Runs", control: "Search logs", caption: "Find a line in the job output", image: new URL("../assets/welcome/run.png", import.meta.url).href },
  settings: { number: 4, section: "Settings", control: "Shared default model", caption: "Choose defaults for future runs", image: new URL("../assets/welcome/settings.png", import.meta.url).href },
} as const;
export type IllustrationKind = keyof typeof screens;

export function OnboardingIllustration({ kind }: { kind: IllustrationKind }) {
  const screen = screens[kind];
  const focus = highlights[kind];
  return <figure className="onboarding-image">
    <div className="onboarding-screen"><img draggable={false} src={screen.image} alt={`${screen.section}: ${screen.control} is highlighted. ${screen.caption}.`} />
      <span className="onboarding-highlight" aria-hidden="true" style={{ left: `${focus.x}%`, top: `${focus.y}%`, width: `${focus.width}%`, height: `${focus.height}%` }}><span>{screen.number}</span></span>
    </div>
    <figcaption><span>{screen.number}</span>{screen.caption}</figcaption>
  </figure>;
}
