'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from 'react';
import { RadarMark } from '@/components/brand/RadarMark';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { Button } from '@/components/ui/Button';
import { ErrorState } from '@/components/ui/ErrorState';
import { IconArrowRight, IconShield } from '@/components/ui/Icons';
import { Input } from '@/components/ui/Input';
import { useLogin } from '@/lib/api/hooks';
import { getSessionSnapshot, subscribeToSession, type SessionState } from '@/lib/auth/session';
import { APP_NAME } from '@/lib/config';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';
import styles from './login.module.css';

const SERVER_SNAPSHOT: SessionState = { status: 'unknown', user: null };

/** Only same-origin, absolute-path redirects — never an attacker-supplied URL. */
function safeRedirect(target: string | null): string {
  if (!target) return '/dashboard';
  if (!target.startsWith('/') || target.startsWith('//')) return '/dashboard';
  return target;
}

/** The principles the product is built on, from docs/REQUIREMENTS.md §7. */
const PRINCIPLES = [
  {
    id: 'CON-001',
    title: (
      <>
        Evidence, <em>not accusation.</em>
      </>
    ),
    body: 'The nearest vessel is not automatically responsible. Rankings prioritise enquiry; when the evidence cannot separate candidates, the labels are capped.',
  },
  {
    id: 'CON-002',
    title: (
      <>
        A gap is <em>not guilt.</em>
      </>
    ),
    body: 'Missing AIS reports lower confidence in a track. They can never raise a vessel’s score.',
  },
  {
    id: 'CON-008',
    title: (
      <>
        An area, <em>never a pin.</em>
      </>
    ),
    body: 'The origin is a probability region with nested contours — no code path emits a single discharge coordinate.',
  },
];

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const login = useLogin();
  const root = useRef<HTMLElement | null>(null);
  const [principle, setPrinciple] = useState(0);

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

  useEffect(() => {
    if (prefersReducedMotion()) return;
    const timer = setInterval(() => setPrinciple((i) => (i + 1) % PRINCIPLES.length), 5200);
    return () => clearInterval(timer);
  }, []);

  useGSAP(
    () => {
      if (prefersReducedMotion()) return;
      const q = gsap.utils.selector(root);
      gsap
        .timeline({ defaults: { ease: 'expo.out' } })
        .from(q('[data-scope]'), { autoAlpha: 0, scale: 0.9, rotate: -10, duration: 1.8 }, 0)
        .from(q('[data-intro]'), { autoAlpha: 0, y: 20, duration: 1, stagger: 0.07 }, 0.15);
    },
    { scope: root },
  );

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
    <main className={styles.shell} id="main-content" ref={root}>
      <section className={styles.visual} aria-label="About SPILLTRACE">
        <svg className={styles.scope} viewBox="0 0 600 600" aria-hidden="true" data-scope="">
          <defs>
            <linearGradient id="lg-sweep" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="var(--color-accent-2)" stopOpacity="0.4" />
              <stop offset="100%" stopColor="var(--color-accent-2)" stopOpacity="0" />
            </linearGradient>
            <radialGradient id="lg-slick" cx="45%" cy="45%" r="60%">
              <stop offset="0%" stopColor="var(--map-spill)" stopOpacity="0.85" />
              <stop offset="100%" stopColor="var(--map-spill)" stopOpacity="0.08" />
            </radialGradient>
          </defs>
          <g fill="none" stroke="var(--color-accent)" strokeOpacity="0.22">
            <circle cx="300" cy="300" r="90" />
            <circle cx="300" cy="300" r="180" />
            <circle cx="300" cy="300" r="270" strokeOpacity="0.4" />
            <path d="M30 300H570M300 30V570" strokeDasharray="2 6" />
          </g>
          <g fill="none" stroke="var(--color-accent-2)" strokeOpacity="0.5">
            <circle className={styles.ring} cx="300" cy="300" r="150" />
            <circle className={styles.ring} cx="300" cy="300" r="150" />
            <circle className={styles.ring} cx="300" cy="300" r="150" />
          </g>
          <g>
            <ellipse
              cx="250"
              cy="350"
              rx="110"
              ry="70"
              fill="var(--map-origin)"
              fillOpacity="0.12"
              stroke="var(--map-origin)"
              strokeOpacity="0.5"
              strokeDasharray="4 5"
            />
            <ellipse
              cx="250"
              cy="350"
              rx="64"
              ry="40"
              fill="none"
              stroke="var(--map-origin)"
              strokeOpacity="0.75"
            />
          </g>
          <path
            d="M300 280c32-20 72-25 114-14 36 9 66 30 101 35 29 4 56-5 82 7 20 8 29 27 21 43-10 18-37 21-60 18-45-6-85-27-131-30-40-3-79 9-117-4-26-9-43-34-36-53 5-14 17-19 26-2z"
            fill="url(#lg-slick)"
            stroke="var(--map-spill)"
            strokeOpacity="0.6"
            transform="translate(-70 10) scale(0.85)"
          />
          <g
            fill="none"
            stroke="var(--map-vessel)"
            strokeOpacity="0.7"
            strokeWidth="1.5"
            strokeDasharray="8 10"
          >
            <path d="M40 470 C150 430 220 390 300 350 S470 280 580 250" />
            <path d="M80 200 C180 230 250 290 330 320 S470 360 570 350" />
          </g>
          <g className={styles.sweep}>
            <path d="M300 300 L585 200 A302 302 0 0 1 585 400 Z" fill="url(#lg-sweep)" />
          </g>
          <circle className={styles.blip} cx="400" cy="250" r="4" fill="var(--confidence-3)" />
          <circle cx="300" cy="300" r="3.5" fill="var(--color-accent-2)" />
        </svg>

        <Link href="/" className={styles.brand} data-intro="">
          <RadarMark size={32} />
          {APP_NAME}
        </Link>

        <div className={styles.principles} data-intro="">
          <p className={cx('eyebrow', styles.principleEyebrow)}>Built on nine safeguards</p>
          <div className={styles.principleStage} aria-live="off">
            {PRINCIPLES.map((item, index) => (
              <div
                key={item.id}
                className={cx(styles.principle, index === principle && styles.principleActive)}
                aria-hidden={index !== principle}
              >
                <p className={styles.principleTitle}>{item.title}</p>
                <p className={styles.principleBody}>
                  <code>{item.id}</code> · {item.body}
                </p>
              </div>
            ))}
          </div>
          <div className={styles.dots} aria-hidden="true">
            {PRINCIPLES.map((item, index) => (
              <span
                key={item.id}
                className={cx(styles.dot, index === principle && styles.dotActive)}
              />
            ))}
          </div>
        </div>

        <p className={styles.visualFoot} data-intro="">
          Smart India Hackathon 2026 · SIH26143 · Team OnlyBans
        </p>
      </section>

      <section className={styles.panel}>
        <div className={styles.card}>
          <div
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}
            data-intro=""
          >
            <div>
              <h1 className={styles.title}>Welcome back</h1>
              <p className={styles.subtitle}>Sign in to open and run investigations.</p>
            </div>
            <ThemeToggle />
          </div>

          {/* Validation errors are shown per field; anything else (401, 429,
              network) is a whole-form condition and belongs above the fields. */}
          {login.isError && Object.keys(fieldErrors).length === 0 ? (
            <div className={styles.error}>
              <ErrorState compact error={login.error} />
            </div>
          ) : null}

          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <div data-intro="">
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
            </div>
            <div data-intro="">
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
            </div>
            <div data-intro="">
              <Button
                type="submit"
                variant="primary"
                size="lg"
                fullWidth
                loading={login.isPending}
                loadingLabel="Signing in"
                disabled={disabled}
                trailingIcon={<IconArrowRight size={16} />}
              >
                Sign in
              </Button>
            </div>
          </form>

          <p className={styles.security} data-intro="">
            <IconShield size={15} />
            <span>
              Sessions use a short-lived access token held in memory and a refresh token in an
              httpOnly cookie. No provider credential of any kind is present in this application.
            </span>
          </p>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-5)' }} data-intro="">
            <Link href="/" className={styles.back}>
              <IconArrowRight size={13} /> Back to the overview
            </Link>
            <Link href="/transparency" className={styles.forward}>
              How SPILLTRACE is held to account <IconArrowRight size={13} />
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
