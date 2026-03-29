import type { ReviewComment } from "@/types/api";

import { Table } from "@/components/ui/table";

export function ReviewCommentsTab({ comments }: { comments: ReviewComment[] }) {
  return (
    <Table>
      <thead className="bg-secondary/60">
        <tr>
          <th className="px-4 py-3 text-left">File</th>
          <th className="px-4 py-3 text-left">Line</th>
          <th className="px-4 py-3 text-left">Severity</th>
          <th className="px-4 py-3 text-left">Comment</th>
        </tr>
      </thead>
      <tbody>
        {comments.map((comment) => (
          <tr key={comment.id} className="border-t border-border">
            <td className="px-4 py-3">{comment.file_path ?? "General"}</td>
            <td className="px-4 py-3">{comment.line_number ?? "-"}</td>
            <td className="px-4 py-3">{comment.severity}</td>
            <td className="px-4 py-3">{comment.comment}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
