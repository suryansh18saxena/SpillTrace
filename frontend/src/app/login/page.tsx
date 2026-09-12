import type { Metadata } from 'next';
import { Suspense } from 'react';
import { RadarMark } from '@/components/brand/RadarMark';
import { LoginForm } from './LoginForm';
import styles from './login.module.css';

export const metadata: Metadata = {
  title: 'Sign in',
  description: 'Sign in to SPILLTRACE to open and run oil-spill attribution investigations.',
};

/**
 * UI-001 — Login.
 *
 * The form is a separate client component behind `<Suspense>` because it reads
 * the `?redirect=` parameter with `useSearchParams`, which Next 15 requires to
 * sit inside a suspense boundary so the rest of the page can still prerender.
 */
export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className={styles.loading} role="status" aria-label="Loading sign-in">
          <RadarMark size={48} />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
