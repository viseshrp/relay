type Diagnostic = {
  message: string;
  context?: {
    field?: string;
    line?: string;
    column?: string;
    severity?: "error" | "warning";
    /** The deprecated built-in reference a warning is about. */
    deprecated?: string;
    /** The removed built-in reference an error is about. */
    removed?: string;
    /** The captured file a warning is about, when it is not the open source. */
    source?: string;
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
