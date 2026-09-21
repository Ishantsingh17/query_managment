"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { AuditRequestDetail } from "./types";

const POLL_INTERVAL_MS = 1000;

/**
 * Poll a request while it is still working, and stop once it settles.
 *
 * `is_active` is decided by the backend from the request status, so the UI
 * does not need its own notion of which statuses are still in flight.
 *
 * A request can become active again after the loop has already stopped: it
 * halts on NEEDS_INPUT, the auditor answers, and retrieval resumes. So "the
 * loop is idle" is tracked separately from "the component is unmounted" -
 * conflating the two leaves the screen frozen on the pre-answer payload.
 */
export function useRequestPolling(requestId: string) {
  const [detail, setDetail] = useState<AuditRequestDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmounted = useRef(false);
  const polling = useRef(false);

  const fetchOnce = useCallback(async () => {
    try {
      const next = await api.getRequest(requestId);
      if (unmounted.current) return null;
      setDetail(next);
      setError(null);
      return next;
    } catch (err) {
      if (!unmounted.current) {
        setError(
          err instanceof ApiError ? err.message : "Could not load the request.",
        );
      }
      return null;
    } finally {
      if (!unmounted.current) setLoading(false);
    }
  }, [requestId]);

  const loop = useCallback(async () => {
    if (unmounted.current) {
      polling.current = false;
      return;
    }
    const next = await fetchOnce();
    if (unmounted.current) {
      polling.current = false;
      return;
    }
    if (next?.is_active) {
      timer.current = setTimeout(() => void loop(), POLL_INTERVAL_MS);
    } else {
      // Settled. Mark the loop idle so it can be restarted later.
      polling.current = false;
    }
  }, [fetchOnce]);

  const start = useCallback(() => {
    if (unmounted.current || polling.current) return;
    polling.current = true;
    void loop();
  }, [loop]);

  /** Fetch now, and pick polling back up if the request is working again. */
  const refresh = useCallback(async () => {
    const next = await fetchOnce();
    if (next?.is_active) start();
    return next;
  }, [fetchOnce, start]);

  useEffect(() => {
    unmounted.current = false;
    start();

    return () => {
      unmounted.current = true;
      polling.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [start]);

  return { detail, error, loading, refresh };
}
