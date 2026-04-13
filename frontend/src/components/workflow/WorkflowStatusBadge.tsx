import { StatusBadge } from "@/components/shared/StatusBadge";

export function WorkflowStatusBadge({ status }: { status: string }) {
  return <StatusBadge status={status} />;
}
