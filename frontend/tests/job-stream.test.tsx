import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useJobStream } from '@/lib/api/useJobStream';
import { resetSessionForTests, setSession } from '@/lib/auth/session';
import type { ReactNode } from 'react';

const CASE_ID = '375c5e4d-6f75-446b-be1c-82a9867921a8';

class StubEventSource {
  static instances: StubEventSource[] = [];
  readonly listeners = new Map<string, Set<(event: Event) => void>>();
  closed = false;

  constructor(
    readonly url: string,
    readonly init?: EventSourceInit,
  ) {
    StubEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data?: unknown) {
    const event =
      data === undefined
        ? new Event(type)
        : Object.assign(new Event(type), { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function signIn() {
  setSession({
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 900,
    user: { id: 'u1', email: 'analyst@spilltrace.example.com', role: 'analyst' },
  });
}

afterEach(() => {
  StubEventSource.instances = [];
  resetSessionForTests();
});

/**
 * NFR-003.
 *
 * The SSE stream is an optimisation, never a dependency. Every path that cannot
 * produce a live stream — no `EventSource`, no token, a dropped connection —
 * must land on `polling`, because the alternative is an analyst watching a
 * progress bar that silently stopped updating.
 */
describe('useJobStream — the fallback is the point', () => {
  it('falls back to polling when the browser has no EventSource', () => {
    signIn();
    vi.stubGlobal('EventSource', undefined);

    const { result } = renderHook(() => useJobStream(CASE_ID), { wrapper });

    expect(result.current.transport).toBe('polling');
    expect(result.current.shouldPoll).toBe(true);
    expect(result.current.reason).toMatch(/EventSource/i);
  });

  it('falls back to polling when there is no access token to hand the stream', () => {
    vi.stubGlobal('EventSource', StubEventSource);

    const { result } = renderHook(() => useJobStream(CASE_ID), { wrapper });

    expect(result.current.transport).toBe('polling');
    expect(result.current.shouldPoll).toBe(true);
    expect(StubEventSource.instances).toHaveLength(0);
  });

  it('stays idle, and opens nothing, when disabled or given no case', () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    const { result } = renderHook(() => useJobStream(CASE_ID, { enabled: false }), { wrapper });

    expect(result.current.transport).toBe('idle');
    expect(StubEventSource.instances).toHaveLength(0);
  });

  it('polls while the stream is still connecting, then stops once it opens', async () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    const { result } = renderHook(() => useJobStream(CASE_ID), { wrapper });

    expect(result.current.transport).toBe('connecting');
    expect(result.current.shouldPoll).toBe(true);

    const source = StubEventSource.instances[0];
    expect(source).toBeDefined();
    act(() => source?.emit('open'));

    await waitFor(() => expect(result.current.transport).toBe('stream'));
    expect(result.current.shouldPoll).toBe(false);
  });

  it('carries the token as a query parameter, because EventSource cannot set a header', () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    renderHook(() => useJobStream(CASE_ID), { wrapper });

    const source = StubEventSource.instances[0];
    expect(source?.url).toContain(`/cases/${CASE_ID}/events`);
    expect(source?.url).toContain('access_token=test-access-token');
  });

  it('closes the stream and reverts to polling when it drops', async () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    const { result } = renderHook(() => useJobStream(CASE_ID), { wrapper });
    const source = StubEventSource.instances[0];

    act(() => source?.emit('open'));
    await waitFor(() => expect(result.current.transport).toBe('stream'));

    act(() => source?.emit('error'));

    await waitFor(() => expect(result.current.transport).toBe('polling'));
    expect(result.current.shouldPoll).toBe(true);
    expect(source?.closed).toBe(true);
    expect(result.current.reason).toMatch(/dropped/i);
  });

  it('records progress frames and ignores frames for another case', async () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    const { result } = renderHook(() => useJobStream(CASE_ID), { wrapper });
    const source = StubEventSource.instances[0];

    act(() =>
      source?.emit('progress', {
        job_id: 'job-1',
        case_id: CASE_ID,
        job_type: 'drift.hindcast',
        progress: 42,
        step: 'advecting particles',
      }),
    );
    await waitFor(() => expect(result.current.lastEvent?.progress).toBe(42));
    expect(result.current.lastEvent?.type).toBe('progress');

    act(() => source?.emit('progress', { job_id: 'job-9', case_id: 'another-case', progress: 99 }));
    expect(result.current.lastEvent?.progress).toBe(42);
  });

  it('survives a malformed frame instead of tearing the stream down', async () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    const { result } = renderHook(() => useJobStream(CASE_ID), { wrapper });
    const source = StubEventSource.instances[0];

    act(() => source?.emit('open'));
    await waitFor(() => expect(result.current.transport).toBe('stream'));

    act(() => {
      const event = Object.assign(new Event('progress'), { data: 'not json' });
      for (const listener of source?.listeners.get('progress') ?? []) listener(event);
    });

    expect(result.current.transport).toBe('stream');
    expect(result.current.lastEvent).toBeNull();
  });

  it('closes the stream when the screen unmounts', () => {
    signIn();
    vi.stubGlobal('EventSource', StubEventSource);

    const { unmount } = renderHook(() => useJobStream(CASE_ID), { wrapper });
    const source = StubEventSource.instances[0];

    unmount();
    expect(source?.closed).toBe(true);
  });
});
