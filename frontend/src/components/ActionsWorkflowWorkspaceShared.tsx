type Diagnostic = {
  message: string;
  context?: { field?: string; line?: string; column?: string };
};
type Trigger = { workflow_key: string; event: string; enabled: boolean };
const encoded = (key: string) =>
  key.split("/").map(encodeURIComponent).join("/");
export { type Diagnostic, type Trigger, encoded };
