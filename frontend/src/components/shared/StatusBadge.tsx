import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const statusClasses: Record<string, string> = {
  queued: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-100",
  running: "bg-sky-200 text-sky-800 dark:bg-sky-900/60 dark:text-sky-100 animate-pulse",
  starting: "bg-sky-200 text-sky-800 dark:bg-sky-900/60 dark:text-sky-100",
  retrying: "bg-amber-200 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100",
  succeeded: "bg-emerald-200 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100",
  failed: "bg-rose-200 text-rose-900 dark:bg-rose-900/50 dark:text-rose-100",
  cancelled: "bg-orange-200 text-orange-900 dark:bg-orange-900/50 dark:text-orange-100",
  stale: "bg-slate-200/60 text-slate-500 dark:bg-slate-800/60 dark:text-slate-400",
  waiting_for_user: "bg-yellow-200 text-yellow-900 dark:bg-yellow-900/50 dark:text-yellow-100",
  completed_with_unresolved_findings: "bg-emerald-200 text-emerald-900 ring-2 ring-amber-400/80 dark:bg-emerald-900/50 dark:text-emerald-100",
  completed: "bg-emerald-200 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge className={cn("border-none", statusClasses[status] ?? "bg-secondary text-secondary-foreground")}>{status.replaceAll("_", " ")}</Badge>;
}
