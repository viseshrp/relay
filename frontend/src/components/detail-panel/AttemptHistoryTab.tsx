import type { AttemptDetail } from "@/types/api";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function AttemptHistoryTab({
  attempts,
  onSelect,
}: {
  attempts: AttemptDetail[];
  onSelect: (attemptNumber: number) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="border-t-0">
          <TableHead>Attempt</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {attempts.map((attempt) => (
          <TableRow key={attempt.id}>
            <TableCell>{attempt.attempt_number}</TableCell>
            <TableCell>{attempt.status}</TableCell>
            <TableCell>{attempt.started_at ? new Date(attempt.started_at).toLocaleString() : "-"}</TableCell>
            <TableCell>
              <Button variant="ghost" onClick={() => onSelect(attempt.attempt_number)}>
                View
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
