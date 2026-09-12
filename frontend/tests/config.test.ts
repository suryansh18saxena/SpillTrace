import { describe, expect, it } from 'vitest';
import { resolveApiBaseUrl } from '@/lib/config';

describe('resolveApiBaseUrl', () => {
  it('defaults to the local API port when nothing is configured', () => {
    expect(resolveApiBaseUrl(undefined, 'https://ignored.example')).toBe('http://localhost:8000');
  });

  it('uses a configured origin and drops trailing slashes', () => {
    expect(resolveApiBaseUrl('https://api.example.org/', 'https://app.example.org')).toBe(
      'https://api.example.org',
    );
  });

  it('follows the page origin when configured as same-origin', () => {
    expect(resolveApiBaseUrl('', 'https://18-212-85-28.sslip.io')).toBe(
      'https://18-212-85-28.sslip.io',
    );
    expect(resolveApiBaseUrl('  ', 'http://18.212.85.28')).toBe('http://18.212.85.28');
  });

  it('stays path-relative during the server render of a same-origin build', () => {
    expect(resolveApiBaseUrl('', undefined)).toBe('');
  });
});
