import type { ReviewComment } from "@/types/api";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function ReviewCommentsTab({ comments }: { comments: ReviewComment[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="border-t-0">
          <TableHead>File</TableHead>
          <TableHead>Line</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Comment</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {comments.map((comment) => (
          <TableRow key={comment.id}>
            <TableCell>{comment.file_path ?? "General"}</TableCell>
            <TableCell>{comment.line_number ?? "-"}</TableCell>
            <TableCell>{comment.severity}</TableCell>
            <TableCell>{comment.comment}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
