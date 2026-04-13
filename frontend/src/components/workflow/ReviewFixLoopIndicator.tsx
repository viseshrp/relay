import { Badge } from "@/components/ui/badge";

export function ReviewFixLoopIndicator({ count, limit }: { count: number; limit: number }) {
  if (count <= 0) {
    return null;
  }

  return (
    <div className="relative h-16 w-16 text-muted-foreground">
      <svg className="absolute -right-8 top-0 h-full w-8" viewBox="0 0 32 100" fill="none" aria-hidden="true">
        <path d="M 4 100 C 4 50, 28 50, 28 0" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" />
        <polygon points="26,4 30,0 28,8" fill="currentColor" />
      </svg>
      <Badge variant="secondary" className="absolute -right-12 top-1/2 -translate-y-1/2 text-xs">
        {count}/{limit}
      </Badge>
    </div>
  );
}
