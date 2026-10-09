type Binding = {
  scope: string;
  name: string;
  kind: string;
  value: string;
  source: string;
  reference: string;
  revision: string;
};
type Environment = {
  name: string;
  approval_required: boolean;
  wait_minutes: number;
  branches: string[];
  url: string;
};
type Template = { id: string; name: string; description?: string };
export { type Binding, type Environment, type Template };
