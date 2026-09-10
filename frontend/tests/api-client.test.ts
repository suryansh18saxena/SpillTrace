import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, apiRequest, buildUrl, onUnauthenticated } from '@/lib/api/client';
import { clearSession, getAccessToken, resetSessionForTests, setSession } from '@/lib/auth/session';
import { API_BASE_URL } from '@/lib/config';
import type { LoginResponse } from '@/lib/api/types';

/** Build a `Response` the way the API would return one. */
function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const SESSION: LoginResponse = {
  access_token: 'token-1',
  token_type: 'bearer',
  expires_in: 900,
  user: { id: 'u1', email: 'analyst@example.test', role: 'analyst' },
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetSessionForTests();
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  resetSessionForTests();
});

describe('buildUrl', () => {
  it('prefixes the versioned API path', () => {
    expect(buildUrl('/cases')).toBe(`${API_BASE_URL}/api/v1/cases`);
  });

  it('leaves unversioned health checks alone', () => {
    expect(buildUrl('/health')).toBe(`${API_BASE_URL}/health`);
  });

  it('omits undefined, null and empty query values', () => {
    const url = buildUrl('/cases', { limit: 25, offset: 0, q: '', status: undefined, to: null });
    expect(url).toBe(`${API_BASE_URL}/api/v1/cases?limit=25&offset=0`);
  });

  it('repeats array query values', () => {
    expect(buildUrl('/cases', { status: ['DRAFT', 'RUNNING'] })).toBe(
      `${API_BASE_URL}/api/v1/cases?status=DRAFT&status=RUNNING`,
    );
  });
});

describe('apiRequest — success paths', () => {
  it('parses a JSON body', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }));
    await expect(apiRequest('/cases')).resolves.toEqual({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
    });
  });

  it('returns undefined for 204 No Content', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(apiRequest('/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });

  it('attaches the in-memory bearer token', async () => {
    setSession(SESSION);
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));
    await apiRequest('/auth/me');

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer token-1');
    // The refresh cookie must ride along on every call, or a rotation is lost.
    expect(init.credentials).toBe('include');
  });

  it('sends no Authorization header when there is no session', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));
    await apiRequest('/cases');
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['Authorization']).toBeUndefined();
  });
});

describe('apiRequest — error mapping', () => {
  it('maps the documented error envelope onto ApiError', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: 'CASE_NOT_FOUND',
            message: 'Case not found.',
            details: { case_id: 'abc' },
            request_id: '01JREQUEST',
          },
        },
        { status: 404 },
      ),
    );

    const error = await apiRequest('/cases/abc').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.code).toBe('CASE_NOT_FOUND');
    expect(apiError.message).toBe('Case not found.');
    expect(apiError.status).toBe(404);
    expect(apiError.details).toEqual({ case_id: 'abc' });
    expect(apiError.requestId).toBe('01JREQUEST');
    expect(apiError.isNotFound).toBe(true);
    expect(apiError.isRetryable).toBe(false);
  });

  it.each([
    [400, 'BAD_REQUEST'],
    [403, 'FORBIDDEN'],
    [409, 'CONFLICT'],
    [422, 'VALIDATION_ERROR'],
    [429, 'RATE_LIMITED'],
    [500, 'SERVER_ERROR'],
    [503, 'SERVICE_UNAVAILABLE'],
  ])('derives a code from status %i when the body is not an envelope', async (status, code) => {
    fetchMock.mockResolvedValueOnce(new Response('', { status }));
    const error = (await apiRequest('/cases').catch((caught: unknown) => caught)) as ApiError;
    expect(error.code).toBe(code);
    expect(error.status).toBe(status);
    // Never a stack trace, always something an analyst can read (NFR-011).
    expect(error.message.length).toBeGreaterThan(0);
    expect(error.message).not.toMatch(/\n\s*at\s/);
    expect(error.message).not.toMatch(/Traceback|File "|\.py:\d+/);
  });

  it('falls back to the X-Request-ID header when the body carries no request id', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('', { status: 503, headers: { 'X-Request-ID': '01JHEADER' } }),
    );
    const error = (await apiRequest('/cases').catch((caught: unknown) => caught)) as ApiError;
    expect(error.requestId).toBe('01JHEADER');
    expect(error.isRetryable).toBe(true);
  });

  it('salvages FastAPI 422 detail entries into fieldErrors', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { detail: [{ loc: ['body', 'end_time'], msg: 'must be after start_time' }] },
        { status: 422 },
      ),
    );
    const error = (await apiRequest('/cases', { method: 'POST' }).catch(
      (caught: unknown) => caught,
    )) as ApiError;
    expect(error.code).toBe('VALIDATION_ERROR');
    expect(error.fieldErrors).toEqual({ end_time: 'must be after start_time' });
    expect(error.isValidation).toBe(true);
  });

  it('maps a network failure onto NETWORK_ERROR rather than leaking the fetch error', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const error = (await apiRequest('/cases').catch((caught: unknown) => caught)) as ApiError;
    expect(error.code).toBe('NETWORK_ERROR');
    expect(error.status).toBe(0);
    expect(error.isRetryable).toBe(true);
    expect(error.message).toContain('Could not reach the SPILLTRACE API');
  });

  it('rejects a non-JSON success body instead of returning a string', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('<!doctype html><title>proxy</title>', {
        status: 200,
        headers: { 'Content-Type': 'text/html' },
      }),
    );
    const error = (await apiRequest('/cases').catch((caught: unknown) => caught)) as ApiError;
    expect(error.code).toBe('MALFORMED_RESPONSE');
    expect(error.isRetryable).toBe(false);
  });

  it('normalises an abort into CANCELLED', () => {
    const cancelled = ApiError.from(new DOMException('aborted', 'AbortError'));
    expect(cancelled.code).toBe('CANCELLED');
    expect(cancelled.isRetryable).toBe(false);
  });

  it('normalises an unknown throw into an ApiError', () => {
    expect(ApiError.from('boom').code).toBe('UNKNOWN');
    expect(ApiError.from(new Error('boom')).message).toBe('boom');
  });
});

describe('apiRequest — 401 handling', () => {
  it('refreshes once and replays the request', async () => {
    setSession(SESSION);

    fetchMock
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(
        jsonResponse({ access_token: 'token-2', token_type: 'bearer', expires_in: 900 }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 'case-1' }));

    await expect(apiRequest('/cases/case-1')).resolves.toEqual({ id: 'case-1' });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${API_BASE_URL}/api/v1/auth/refresh`);
    expect(getAccessToken()).toBe('token-2');

    // The replay must carry the *new* token, not the stale one.
    const replayInit = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect((replayInit.headers as Record<string, string>)['Authorization']).toBe('Bearer token-2');
  });

  it('refreshes at most once, then clears the session and signals the shell', async () => {
    setSession(SESSION);
    const listener = vi.fn();
    const unsubscribe = onUnauthenticated(listener);

    fetchMock
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(new Response('', { status: 401 }));

    const error = (await apiRequest('/cases').catch((caught: unknown) => caught)) as ApiError;

    // Original + refresh only: no second refresh, no retry storm.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(error.isUnauthenticated).toBe(true);
    expect(getAccessToken()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it('never tries to refresh when the failing call is the login itself', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { error: { code: 'INVALID_CREDENTIALS', message: 'Email or password is incorrect.' } },
        { status: 401 },
      ),
    );

    const error = (await api
      .login({ email: 'a@b.test', password: 'nope' })
      .catch((caught: unknown) => caught)) as ApiError;

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(error.code).toBe('INVALID_CREDENTIALS');
  });

  it('shares one refresh between concurrent 401s', async () => {
    setSession(SESSION);

    fetchMock.mockImplementation((input: string) => {
      if (input.endsWith('/auth/refresh')) {
        return Promise.resolve(
          jsonResponse({ access_token: 'token-3', token_type: 'bearer', expires_in: 900 }),
        );
      }
      // First attempt per request 401s; once the token is refreshed, succeed.
      return Promise.resolve(
        getAccessToken() === 'token-3'
          ? jsonResponse({ ok: true })
          : new Response('', { status: 401 }),
      );
    });

    await Promise.all([apiRequest('/cases'), apiRequest('/jobs/1'), apiRequest('/auth/me')]);

    const refreshCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).endsWith('/auth/refresh'),
    );
    expect(refreshCalls).toHaveLength(1);
  });
});

describe('session storage guarantees', () => {
  it('never writes the access token to localStorage or sessionStorage', () => {
    setSession(SESSION);
    expect(getAccessToken()).toBe('token-1');
    expect(window.localStorage.getItem('spilltrace:token')).toBeNull();
    expect(Object.values({ ...window.localStorage })).not.toContain('token-1');
    expect(Object.values({ ...window.sessionStorage })).not.toContain('token-1');
  });

  it('drops the token on clearSession', () => {
    setSession(SESSION);
    clearSession();
    expect(getAccessToken()).toBeNull();
  });
});
