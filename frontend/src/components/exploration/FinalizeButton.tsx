import { Button } from "@/components/ui/button";

export function FinalizeButton({ disabled, onFinalize }: { disabled: boolean; onFinalize: () => Promise<unknown> }) {
  return (
    <Button disabled={disabled} onClick={() => void onFinalize()}>
      Finalize Exploration
    </Button>
  );
}
