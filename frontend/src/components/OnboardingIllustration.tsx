const captions = {
  project: ["Project", "Open a project", "Choose your local Git repository"],
  workflow: ["Workflows", "New workflow", "Start from a template"],
  run: ["Runs", "Search logs", "Follow output as jobs run"],
  settings: ["Settings", "Global defaults", "Choose defaults for future runs"],
} as const;
export type IllustrationKind = keyof typeof captions;

export function OnboardingIllustration({ kind }: { kind: IllustrationKind }) {
  const [section, control, caption] = captions[kind];
  return <svg className="onboarding-image" viewBox="0 0 760 330" role="img" aria-label={`${section}: ${control} is highlighted. ${caption}.`}>
    <rect x="1" y="1" width="758" height="328" rx="12" fill="#f4f6fb" stroke="#dce1ec" />
    <rect x="1" y="1" width="758" height="54" rx="12" fill="white" />
    <g fontFamily="inherit" fontSize="15" fill="#27334b"><text x="22" y="34" fill="#3156d3" fontWeight="700">Relay</text><text x="103" y="34">Project</text><text x="285" y="34">Workflows</text><text x="412" y="34">Runs</text><text x="490" y="34">Settings</text><text x="681" y="34">Help</text></g>
    <rect x="20" y="78" width="176" height="230" rx="7" fill="white" />
    <g fontFamily="inherit" fill="#27334b"><text x="38" y="106" fontSize="17" fontWeight="700">{section}</text><rect x="31" y="124" width="154" height="41" rx="6" fill="#e8edfc" /><text x="41" y="150" fontSize="14" fill="#3156d3">{kind === "run" ? "Summary" : control}</text><text x="41" y="195" fontSize="13">{kind === "settings" ? "Project defaults" : "Plan"}</text><text x="41" y="235" fontSize="13">{kind === "settings" ? "Storage" : "Implement"}</text><text x="41" y="275" fontSize="13">{kind === "settings" ? "Guided tour" : "Review"}</text></g>
    <rect x="216" y="78" width="524" height="230" rx="7" fill="white" />
    <g fontFamily="inherit" fill="#27334b"><text x="239" y="108" fontSize="18" fontWeight="700">{caption}</text>
      {kind === "run" ? <><rect x="237" y="128" width="480" height="40" rx="6" fill="#f4f6fb" stroke="#dce1ec" /><text x="251" y="154" fontSize="15">Search logs</text><rect x="237" y="187" width="480" height="98" rx="6" fill="#0f172a" /><text x="253" y="212" fontSize="13" fill="#a5b4fc">1  Agent · Preparing a plan</text><text x="253" y="242" fontSize="13" fill="#6ee7b7">2  Command · Tests passed</text><text x="253" y="272" fontSize="13" fill="#f1f5f9">3  Review · Waiting for you</text></>
      : kind === "workflow" ? <><path d="M367 208h45m130 0h45" stroke="#a3aec2" strokeWidth="2" />{["Plan", "Implement", "Review"].map((label, i) => <g key={label}><rect x={237 + i * 166} y="183" width="130" height="50" rx="6" fill="#f4f6fb" stroke="#3156d3" /><text x={255 + i * 166} y="213" fontSize="14">{label}</text></g>)}<text x="238" y="276" fontSize="14">Run workflow → Summary → Job logs</text></>
      : <><rect x="237" y="128" width="480" height="51" rx="6" fill="#f4f6fb" stroke="#dce1ec" /><text x="254" y="160" fontSize="15">{kind === "project" ? "Repository folder" : "Model and thinking effort"}</text><rect x="237" y="200" width="480" height="50" rx="6" fill="#e8edfc" /><text x="254" y="231" fontSize="15">{kind === "project" ? "Open project" : "Shared commands and variables"}</text><text x="238" y="282" fontSize="13">{kind === "project" ? "Your code and branch stay in place." : "?  Learn what each setting changes."}</text></>}
    </g>
    <g fill="none" stroke="#ce6a14" strokeWidth="3" strokeDasharray="8 4">
      {kind === "run" ? <ellipse cx="475" cy="148" rx="248" ry="31" /> : <ellipse cx="107" cy="146" rx="88" ry="32" />}
    </g>
  </svg>;
}
