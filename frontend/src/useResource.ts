import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";

export function useResource<T>(path: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    key: string | null;
    data: T | null;
    error: string | null;
    loading: boolean;
  }>({ key: path, data: null, error: null, loading: Boolean(path) });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setState((current) => ({
      key: path,
      data: current.key === path ? current.data : null,
      error: null,
      loading: true,
    }));
    void api<T>(path, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted)
          setState({ key: path, data, error: null, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState((current) => ({
            ...current,
            error: errorMessage(error),
            loading: false,
          }));
      });
    return () => controller.abort();
  }, [path, revision]);
  const reload = useCallback(() => setRevision((current) => current + 1), []);
  return {
    ...(state.key === path
      ? state
      : { data: null, error: null, loading: Boolean(path) }),
    reload,
  };
}
