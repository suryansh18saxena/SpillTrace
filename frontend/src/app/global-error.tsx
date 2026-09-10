'use client';

/**
 * Last-resort boundary: catches failures in the root layout itself, where the
 * normal `error.tsx` has no shell to render into. It must therefore supply its
 * own <html>/<body> and cannot rely on the design tokens having loaded, so the
 * few styles it needs are inline.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: '#0b0f14',
          color: '#e6edf5',
          fontFamily: 'ui-sans-serif, system-ui, sans-serif',
          padding: '2rem',
        }}
      >
        <main style={{ maxWidth: '34rem', textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.25rem', marginBottom: '0.75rem' }}>
            SPILLTRACE failed to start
          </h1>
          <p style={{ fontSize: '0.875rem', color: '#a5b3c4', lineHeight: 1.6 }}>
            The application shell could not be rendered.
            {error.digest ? ` Reference ${error.digest}.` : ''}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: '1.25rem',
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: '1px solid #4f8ff7',
              background: '#4f8ff7',
              color: '#06101f',
              font: 'inherit',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Reload
          </button>
        </main>
      </body>
    </html>
  );
}
