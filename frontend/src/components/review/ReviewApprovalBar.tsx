import { useState } from "react";

import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Button } from "@/components/ui/button";

export function ReviewApprovalBar({
  onApprove,
  onFix,
  onCancel,
}: {
  onApprove: () => Promise<unknown>;
  onFix: () => Promise<unknown> | void;
  onCancel: () => Promise<unknown>;
}) {
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);

  return (
    <>
      <div className="flex flex-wrap gap-3 rounded-[2rem] border border-border bg-card p-4 shadow-panel">
        <Button onClick={() => void onApprove()}>Approve & Complete</Button>
        <Button variant="secondary" onClick={() => void onFix()}>
          Send to Fix
        </Button>
        <Button variant="destructive" onClick={() => setCancelDialogOpen(true)}>
          Cancel Workflow
        </Button>
      </div>
      <ConfirmDialog
        open={cancelDialogOpen}
        title="Cancel Workflow"
        description="Are you sure you want to cancel this workflow? The running process will be killed immediately."
        onOpenChange={setCancelDialogOpen}
        onConfirm={() => {
          setCancelDialogOpen(false);
          void onCancel();
        }}
      />
    </>
  );
}
