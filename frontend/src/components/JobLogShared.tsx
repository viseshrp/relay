import { Fragment } from "react";

const ROW_HEIGHT = 26;
function fullscreenShortcut(event: {
  key: string;
  shiftKey: boolean;
  target: EventTarget | null;
}): boolean {
  return (
    event.key.toLowerCase() === "f" &&
    event.shiftKey &&
    !(event.target instanceof HTMLInputElement) &&
    !(event.target instanceof HTMLTextAreaElement)
  );
}
function Highlight({
  text,
  ranges,
  offset,
}: {
  text: string;
  ranges: Array<{ start: number; end: number }>;
  offset: number;
}) {
  const parts = [];
  let after = 0;
  for (const range of ranges) {
    const start = Math.max(0, range.start - offset);
    const end = Math.min(text.length, range.end - offset);
    if (end <= start) continue;
    parts.push(
      <Fragment key={start}>
        {text.slice(after, start)}
        <mark>{text.slice(start, end)}</mark>
      </Fragment>,
    );
    after = end;
  }
  return (
    <>
      {parts}
      {text.slice(after)}
    </>
  );
}
export { ROW_HEIGHT, fullscreenShortcut, Highlight };
