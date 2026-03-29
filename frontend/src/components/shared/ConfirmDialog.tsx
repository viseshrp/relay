import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

export function ConfirmDialog({
  open,
  title,
  description,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="mt-2 text-sm text-muted-foreground">{description}</p>
        </div>
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            Confirm
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
