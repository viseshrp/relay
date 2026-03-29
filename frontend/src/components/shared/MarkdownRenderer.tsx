import ReactMarkdown from "react-markdown";

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-stone max-w-none dark:prose-invert">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
