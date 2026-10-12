import { createContext, useContext } from "react";
import type { RunReadQueue } from "../run-monitor";

export const RunReadsContext = createContext<RunReadQueue | null>(null);
export function useRunReads(): RunReadQueue {
  const queue = useContext(RunReadsContext);
  if (!queue)
    throw new Error("Job reads require the selected run's read queue.");
  return queue;
}
