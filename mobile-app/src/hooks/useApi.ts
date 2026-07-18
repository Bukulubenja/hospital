import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';

type UseApiResult<T> = {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => Promise<void>;
};

/** Fetch-on-mount + pull-to-refresh-friendly wrapper around any apiRequest
 * call — every list/detail screen uses this instead of hand-rolled
 * loading/error state. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetcher());
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}

export function errorMessage(error: Error | null): string | null {
  if (!error) return null;
  if (error instanceof ApiError) return error.message;
  return error.message || 'Something went wrong.';
}
