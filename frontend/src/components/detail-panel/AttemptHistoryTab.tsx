import type { AttemptDetail } from "@/types/api";

import { Button } from "@/components/ui/button";
import { Table } from "@/components/ui/table";

export function AttemptHistoryTab({
  attempts,
  onSelect,
}: {
  attempts: AttemptDetail[];
  onSelect: (attemptNumber: number) => void;
}) {
  return (
    <Table>
      <thead className="bg-secondary/60">
        <tr>
          <th className="px-4 py-3 text-left">Attempt</th>
          <th className="px-4 py-3 text-left">Status</th>
          <th className="px-4 py-3 text-left">Started</th>
          <th className="px-4 py-3 text-left">Action</th>
        </tr>
      </thead>
      <tbody>
        {attempts.map((attempt) => (
          <tr key={attempt.id} className="border-t border-border">
            <td className="px-4 py-3">{attempt.attempt_number}</td>
            <td className="px-4 py-3">{attempt.status}</td>
            <td className="px-4 py-3">{attempt.started_at ? new Date(attempt.started_at).toLocaleString() : "-"}</td>
            <td className="px-4 py-3">
              <Button variant="ghost" onClick={() => onSelect(attempt.attempt_number)}>
                View
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
