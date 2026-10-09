# Browser view states

Every main view provides a named loading skeleton, a usable empty state,
an actionable read error, successful content, and an access-denied error.
Authentication expiry returns the owner to login through the shared API layer.
A denied read keeps the server's public error message and offers the same
refresh control used after a temporary read failure.

| View | Loading | Empty | Read error and denied access | Success |
| --- | --- | --- | --- | --- |
| Home | Dashboard and card skeletons | Open your first project | Message and Refresh | Projects, waiting requests, active runs, recent results |
| Workflows | Editor skeleton | No workflows yet; Create workflow | Message and Retry workflow | Shared sidebar, named workflow, canvas and YAML |
| Runs | Run-row skeletons | No runs yet; choose a workflow | Message and Retry | Filtered, paged history with native links |
| Run summary | Reserved header, sidebar and summary blocks | No jobs have been recorded for this run | Message and Retry | Status, graph, requests and artifacts |
| Job log | Job skeleton and log loading state | No attempt yet; no declared outputs; completed empty output is explicit | Message and Retry job | Job steps with their own attempts, output and exit status |
| Settings | Sidebar and form skeletons | Defaults apply when project overrides are absent | Message and Retry settings | Labelled defaults, account, notification and storage forms |

[View-state browser tests](../frontend/e2e/view-states.spec.ts) hold each
view's read, return HTTP 503 and 403, verify the visible recovery control,
and exercise empty responses. Existing authentication tests cover login
expiry. [Visual regression tests](../frontend/e2e/visual-regression.spec.ts)
check all seven main screens, including approvals, at 375, 768 and 1440 px.
They also check cumulative layout shift below 0.1 with delayed API responses
at 375 and 1440 px.

The test server's CSRF-protected `POST /__test__/worst-case` accepts
`{"enabled": true}` for the stress fixture and `{"enabled": false}` for
the normal demo. Its response includes the project, run, approval, job and
workflow keys. It seeds isolated test storage only. The fixture includes
long multilingual names, historical oversized titles, 41 parallel jobs,
20,000 output lines and 154 runs. Tests check all main screens at 320, 768,
1024 and 1440 px. Test-server routes and fixture modules are excluded from
distributions.

Every browser spec uses the shared accessibility fixture. Its final scan
fails on serious or critical WCAG A/AA violations after finite UI animations
finish. Dedicated accessibility specs check landmarks, headings, keyboard
navigation and settings errors. The frontend lint gate also checks React
hooks, JSX accessibility and a 300-line component limit.
