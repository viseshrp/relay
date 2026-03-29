export function ReviewFixLoopIndicator({ count, limit }: { count: number; limit: number }) {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-accent/50 bg-accent/10 p-3 text-sm text-muted-foreground">
      Review-fix loop: {count}/{limit}
    </div>
  );
}
