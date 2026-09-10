'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState, useSyncExternalStore, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ErrorState } from '@/components/ui/ErrorState';
import { Input } from '@/components/ui/Input';
import { IconTarget } from '@/components/ui/Icons';
import { useLogin } from '@/lib/api/hooks';
import { getSessionSnapshot, subscribeToSession, type SessionState } from '@/lib/auth/session';
import { APP_NAME, APP_TAGLINE } from '@/lib/config';
import styles from '@/styles/pages.module.css';

const SERVER_SNAPSHOT: SessionState = { status: 'unknown', user: null };

/** Only same-origin, absolute-path redirects — never an attacker-supplied URL. */
function safeRedirect(target: string | null): string {
  if (!target) return '/cases';
  if (!target.startsWith('/') || target.startsWith('//')) return '/cases';
  return target;
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const login = useLogin();

  const session = useSyncExternalStore(
    subscribeToSession,
    getSessionSnapshot,
    () => SERVER_SNAPSHOT,
  );

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const redirectTo = safeRedirect(searchParams.get('redirect'));

  useEffect(() => {
    if (session.status === 'authenticated') router.replace(redirectTo);
  }, [session.status, redirectTo, router]);

  const fieldErrors = login.error?.fieldErrors ?? {};
  const emailError =
    (submitted && !email ? 'Enter your email address.' : null) ?? fieldErrors['email'];
  const passwordError =
    (submitted && !password ? 'Enter your password.' : null) ?? fieldErrors['password'];

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!email || !password) return;
    login.mutate({ email, password }, { onSuccess: () => router.replace(redirectTo) });
  };

  const disabled = login.isPending || session.status === 'authenticated';

  return (
    <main className={styles.authScreen} id="main-content">
      <div className={styles.authCard}>
        <div className={styles.authBrand}>
          <span className={styles.authBrandMark} aria-hidden="true">
            <IconTarget size={20} />
          </span>
          <span>
            <span className={styles.authTitle}>{APP_NAME}</span>
            <span className={styles.authSubtitle}>{APP_TAGLINE}</span>
          </span>
        </div>

        <Card title="Sign in" description="Analyst access to case investigations.">
          {/* Validation errors are shown per field; anything else (401, 429,
              network) is a whole-form condition and belongs above the fields. */}
          {login.isError && Object.keys(fieldErrors).length === 0 ? (
            <div className={styles.formError}>
              <ErrorState compact error={login.error} />
            </div>
          ) : null}

          <form className={styles.authForm} onSubmit={handleSubmit} noValidate>
            <Input
              label="Email"
              type="email"
              name="email"
              autoComplete="username"
              autoFocus
              required
              spellCheck={false}
              disabled={disabled}
              value={email}
              error={emailError}
              onChange={(event) => setEmail(event.target.value)}
            />
            <Input
              label="Password"
              type="password"
              name="password"
              autoComplete="current-password"
              required
              disabled={disabled}
              value={password}
              error={passwordError}
              onChange={(event) => setPassword(event.target.value)}
            />
            <Button
              type="submit"
              variant="primary"
              size="lg"
              fullWidth
              loading={login.isPending}
              loadingLabel="Signing in"
              disabled={disabled}
            >
              Sign in
            </Button>
          </form>
        </Card>

        <p className={styles.authFooter}>
          Sessions use a short-lived access token held in memory and a refresh token in an httpOnly
          cookie. No provider credential of any kind is present in this application.
        </p>
      </div>
    </main>
  );
}
