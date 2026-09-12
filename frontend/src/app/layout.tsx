import type { Metadata, Viewport } from 'next';
import { GeistMono } from 'geist/font/mono';
import { GeistSans } from 'geist/font/sans';
import { APP_NAME, APP_TAGLINE } from '@/lib/config';
import { MOTION_INIT_SCRIPT, THEME_INIT_SCRIPT } from '@/lib/theme';
import { Providers } from './providers';
// Self-hosted: the CSP allows fonts from 'self' only, so nothing is fetched
// from a font CDN at runtime (CON-004 spirit — no third-party requests).
import '@fontsource/instrument-serif/latin-400.css';
import '@fontsource/instrument-serif/latin-400-italic.css';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: `${APP_NAME} — ${APP_TAGLINE}`,
    template: `%s · ${APP_NAME}`,
  },
  description:
    'SPILLTRACE correlates SAR oil-spill detections, reverse-drift origin probability regions and AIS trajectories to rank candidate vessels for investigation. Results are investigative and probabilistic, never proof of responsibility.',
  applicationName: APP_NAME,
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#03060c' },
    { media: '(prefers-color-scheme: light)', color: '#f2f5fa' },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `suppressHydrationWarning`: the inline script below stamps `data-theme`
    // and `data-motion` on <html> before React hydrates, which is the only way
    // to avoid a flash of the wrong theme. The attribute difference is intentional.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: `${THEME_INIT_SCRIPT}${MOTION_INIT_SCRIPT}` }} />
      </head>
      {/*
        `suppressHydrationWarning` here too: browser extensions (ColorZilla's
        `cz-shortcut-listen`, Grammarly's `data-gr-*`) stamp attributes onto
        <body> before React hydrates. The flag does not cascade from <html>,
        and it only covers this element's own attributes, so real mismatches
        inside the tree are still reported.
      */}
      <body suppressHydrationWarning>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
