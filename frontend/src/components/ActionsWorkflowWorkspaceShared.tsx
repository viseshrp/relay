type Diagnostic = {
  message: string;
  context?: {
    field?: string;
    line?: string;
    column?: string;
    severity?: "error" | "warning";
  };
};
type Trigger = { workflow_key: string; event: string; enabled: boolean };
/** Where validation of the open source stands. */
type Validation = "checking" | "valid" | "invalid" | "empty";
const EMPTY_WORKFLOW =
  "This workflow is empty. Restore the saved source or add a job.";
const VALIDATION_STATUS: Record<Validation, string> = {
  checking: "Validating workflow…",
  valid: "Ready to edit",
  invalid: "Fix the problems above to save.",
  empty: "This workflow is empty.",
};
const encoded = (key: string) =>
  key.split("/").map(encodeURIComponent).join("/");
export {
  type Diagnostic,
  type Trigger,
  type Validation,
  EMPTY_WORKFLOW,
  VALIDATION_STATUS,
  encoded,
};
