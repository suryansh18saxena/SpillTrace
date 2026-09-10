'use client';

/**
 * Live pipeline progress over Server-Sent Events, with a polling fallback.
 *
 * The backend publishes `started` / `progress` / `finished` frames on
 * `GET /cases/{id}/events`. `EventSource` cannot set an `Authorization` header,
 * so that one read-only endpoint accepts the access token as a query parameter —
 * the server documents this narrowly, and it is the only place in this client
 * where a token appears in a URL.
 *
 * The stream is an optimisation, never a dependency. If it cannot connect, if it
 * drops, or if the browser has no `EventSource`, this hook reports
 * `transport: 'polling'` and the caller's queries go back to their bounded 4 s
 * poll. Nothing is ever left showing stale progress because the stream died.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { jobEventsUrl } from '@/lib/api/client';
import { queryKeys } from '@/lib/api/hooks';
import { getAccessToken } from '@/lib/auth/session';
import type { JobEvent, Paginated, Job, Pipeline } from '@/lib/api/types';

export type JobStreamTransport = 'connecting' | 'stream' | 'polling' | 'idle';

export interface JobStreamState {
  /** What is currently keeping the progress panel up to date. */
  transport: JobStreamTransport;
  /** The most recent job frame (never `open` or `keepalive`). */
  lastEvent: JobEvent | null;
  /** Human-readable reason the stream is not in use, when it is not. */
  reason: string | null;
  /** True while the caller's queries should poll instead. */
  shouldPoll: boolean;
}

const JOB_FRAMES = ['started', 'progress', 'finished'] as const;

/** Apply a progress frame to the cached job list without a refetch. */
function patchJobs(
  previous: Paginated<Job> | undefined,
  event: JobEvent,
): Paginated<Job> | undefined {
  if (!previous || !event.job_id) return previous;
  let changed = false;
  const items = previous.items.map((job) => {
    if (job.id !== event.job_id) return job;
    changed = true;
    return {
      ...job,
      ...(typeof event.progress === 'number' ? { progress: event.progress } : {}),
      ...(event.step !== undefined ? { step: event.step } : {}),
      ...(event.status ? { status: event.status } : {}),
      ...(event.type === 'started' ? { status: 'RUNNING' as const } : {}),
    };
  });
  return changed ? { ...previous, items } : previous;
}

/** The same patch, against the compact `/pipeline` projection. */
function patchPipeline(previous: Pipeline | undefined, event: JobEvent): Pipeline | undefined {
  if (!previous?.stages || !event.job_id) return previous;
  let changed = false;
  const stages = previous.stages.map((stage) => {
    if (stage.job_id !== event.job_id) return stage;
    changed = true;
    return {
      ...stage,
      ...(typeof event.progress === 'number' ? { progress: event.progress } : {}),
      ...(event.step !== undefined ? { step: event.step } : {}),
      ...(event.status ? { status: event.status } : {}),
      ...(event.type === 'started' ? { status: 'RUNNING' as const } : {}),
    };
  });
  return changed ? { ...previous, stages } : previous;
}

export interface UseJobStreamOptions {
  /** Set `false` to leave the stream closed (e.g. a settled, archived case). */
  enabled?: boolean;
}

export function useJobStream(
  caseId: string | undefined,
  options: UseJobStreamOptions = {},
): JobStreamState {
  const enabled = options.enabled ?? true;
  const queryClient = useQueryClient();

  const [transport, setTransport] = useState<JobStreamTransport>('idle');
  const [lastEvent, setLastEvent] = useState<JobEvent | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const handleFrame = useCallback(
    (raw: MessageEvent<string>, type: JobEvent['type']) => {
      let payload: JobEvent;
      try {
        payload = { ...(JSON.parse(raw.data) as JobEvent), type };
      } catch {
        // A malformed frame is not worth tearing the stream down for.
        return;
      }
      if (caseId && payload.case_id && payload.case_id !== caseId) return;
      setLastEvent(payload);

      if (!caseId) return;
      queryClient.setQueriesData<Paginated<Job>>(
        { queryKey: [...queryKeys.case(caseId), 'jobs'] },
        (previous) => patchJobs(previous, payload),
      );
      queryClient.setQueryData<Pipeline>(queryKeys.casePipeline(caseId), (previous) =>
        patchPipeline(previous, payload),
      );

      // A finished stage changes more than a progress bar: new detections,
      // layers, drift runs and attributions may now exist.
      if (type === 'finished') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.case(caseId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.cases() });
      }
    },
    [caseId, queryClient],
  );

  useEffect(() => {
    if (!enabled || !caseId) {
      setTransport('idle');
      setReason(null);
      return;
    }

    if (typeof EventSource === 'undefined') {
      setTransport('polling');
      setReason('This browser has no EventSource, so progress is polled every few seconds.');
      return;
    }

    const token = getAccessToken();
    if (!token) {
      setTransport('polling');
      setReason('No access token is available for the stream yet; progress is polled instead.');
      return;
    }

    let source: EventSource;
    try {
      source = new EventSource(jobEventsUrl(caseId, token), { withCredentials: true });
    } catch {
      setTransport('polling');
      setReason('The live stream could not be opened; progress is polled every few seconds.');
      return;
    }

    sourceRef.current = source;
    setTransport('connecting');
    setReason(null);

    const onOpen = () => {
      setTransport('stream');
      setReason(null);
    };
    source.addEventListener('open', onOpen);

    const listeners = JOB_FRAMES.map((type) => {
      const listener = (event: Event) => handleFrame(event as MessageEvent<string>, type);
      source.addEventListener(type, listener);
      return [type, listener] as const;
    });

    const onError = () => {
      // EventSource retries by itself, but a 401 or a dead endpoint would make
      // that an infinite loop of failed requests. Close it and poll instead.
      source.close();
      sourceRef.current = null;
      setTransport('polling');
      setReason('The live progress stream dropped, so progress is polled every few seconds.');
    };
    source.addEventListener('error', onError);

    return () => {
      source.removeEventListener('open', onOpen);
      source.removeEventListener('error', onError);
      for (const [type, listener] of listeners) source.removeEventListener(type, listener);
      source.close();
      sourceRef.current = null;
    };
  }, [caseId, enabled, handleFrame]);

  return useMemo(
    () => ({
      transport,
      lastEvent,
      reason,
      // While the stream is connecting we still poll: a stream that never opens
      // must not leave the analyst watching a frozen progress bar.
      shouldPoll: transport !== 'stream',
    }),
    [transport, lastEvent, reason],
  );
}
