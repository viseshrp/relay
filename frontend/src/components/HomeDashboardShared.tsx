import type { DashboardPage } from "../types";

function mergePage<T extends { id: string }>(
  before: DashboardPage<T>,
  after: DashboardPage<T>,
): DashboardPage<T> {
  const items = new Map(before.items.map((item) => [item.id, item]));
  after.items.forEach((item) => items.set(item.id, item));
  return { items: [...items.values()], next_cursor: after.next_cursor };
}
export { mergePage };
