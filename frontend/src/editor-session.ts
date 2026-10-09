export function editorHolder(): string {
  const existing = sessionStorage.getItem("relay.editor-holder");
  if (existing) return existing;
  const holder = crypto.randomUUID();
  sessionStorage.setItem("relay.editor-holder", holder);
  return holder;
}
