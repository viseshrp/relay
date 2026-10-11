interface ReadEntry {
  controller: AbortController;
  promise: Promise<unknown>;
  subscribers: number;
  abortTimer?: ReturnType<typeof setTimeout>;
}
const reads = new Map<string, ReadEntry>();

export function invalidateReads(): void {
  reads.clear();
}

export function sharedRead<T>(
  key: string,
  signal: AbortSignal | null | undefined,
  read: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  if (signal?.aborted)
    return Promise.reject(new DOMException("Request aborted", "AbortError"));
  let entry = reads.get(key);
  if (!entry) {
    const controller = new AbortController();
    entry = { controller, subscribers: 0, promise: read(controller.signal) };
    reads.set(key, entry);
    const captured = entry;
    // Retain a settled read for this task so simultaneous effect consumers also
    // share it. No stale response is cached across later refreshes.
    void entry.promise
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() =>
        setTimeout(() => {
          if (reads.get(key) === captured) reads.delete(key);
        }, 0),
      );
  }
  const captured = entry;
  clearTimeout(captured.abortTimer);
  captured.subscribers += 1;
  return new Promise<T>((resolve, reject) => {
    let active = true;
    const detach = () => {
      if (!active) return;
      active = false;
      signal?.removeEventListener("abort", aborted);
      captured.subscribers -= 1;
      if (!captured.subscribers)
        captured.abortTimer = setTimeout(() => {
          if (!captured.subscribers) {
            captured.controller.abort();
            if (reads.get(key) === captured) reads.delete(key);
          }
        }, 0);
    };
    const aborted = () => {
      detach();
      reject(new DOMException("Request aborted", "AbortError"));
    };
    signal?.addEventListener("abort", aborted, { once: true });
    captured.promise.then(
      (value) => {
        if (active) {
          detach();
          resolve(value as T);
        }
      },
      (error) => {
        if (active) {
          detach();
          reject(error);
        }
      },
    );
  });
}
