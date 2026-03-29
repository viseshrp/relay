import { Button } from "@/components/ui/button";

export function ReviewApprovalBar({
  onApprove,
  onFix,
  onCancel,
}: {
  onApprove: () => Promise<unknown>;
  onFix: () => void;
  onCancel: () => Promise<unknown>;
}) {
  return (
    <div className="flex flex-wrap gap-3 rounded-[2rem] border border-border bg-card p-4 shadow-panel">
      <Button onClick={() => void onApprove()}>Approve & Complete</Button>
      <Button variant="secondary" onClick={onFix}>
        Send to Fix
      </Button>
      <Button variant="destructive" onClick={() => void onCancel()}>
        Cancel Workflow
      </Button>
    </div>
  );
}
