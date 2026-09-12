import type { NextConfig } from 'next';

/**
 * Basemap tile providers, mirrored from `src/lib/map/basemaps.ts` (next.config
 * cannot import from src). Esri World Imagery / Ocean and CARTO reference maps.
 */
const BASEMAP_HOSTS =
  'https://server.arcgisonline.com https://services.arcgisonline.com https://*.basemaps.cartocdn.com';

/**
 * The API origin the browser talks to. It is our own FastAPI service — never a
 * third party. No third-party credential of any kind is ever exposed to the
 * client bundle (CON-004 / AD-5): the basemap is self-hosted (public/map-style.json)
 * and every provider key stays server-side.
 */
// An empty value means the API is served from the same origin (see
// `resolveApiBaseUrl` in src/lib/config.ts), which `'self'` already covers.
const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000').trim();

/**
 * Content-Security-Policy.
 *
 * `connect-src` is limited to `self` plus our own API origin, which is the
 * mechanical guarantee behind AD-5: the browser cannot reach Copernicus, CMEMS
 * or AISStream even if a future code change tried to.
 *
 * `worker-src blob:` is required by MapLibre GL, which spawns its tile/geometry
 * worker from a blob URL. `img-src blob: data:` covers MapLibre's canvas and
 * the API's probability-raster tiles.
 *
 * `script-src` keeps `'unsafe-inline'` because the App Router inlines its RSC
 * flight payload in <script> tags; a nonce-based policy needs request-time
 * middleware which would opt every route out of static rendering. This is a
 * deliberate, documented trade-off — see docs/SECURITY.md.
 */
function contentSecurityPolicy(isDev: boolean): string {
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "font-src 'self' data:",
    // Public basemap tile hosts (lib/map/basemaps.ts). MapLibre fetches raster
    // tiles with fetch() as ArrayBuffers, so the hosts appear in both img-src
    // and connect-src. No credential is ever sent to them; the Offline basemap
    // makes no external request at all.
    `img-src 'self' data: blob: ${BASEMAP_HOSTS}`,
    "style-src 'self' 'unsafe-inline'",
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    // The evidence report is rendered in a sandboxed `srcdoc` iframe.
    "frame-src 'self' blob:",
    `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ''}`,
    `connect-src 'self' ${apiBaseUrl} ${BASEMAP_HOSTS}${isDev ? ' ws: http://localhost:*' : ''}`,
  ].join('; ');
}

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    // Linting is a separate, explicit gate (`npm run lint`) so that a lint
    // failure cannot be silently skipped or silently block a production build.
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  async headers() {
    const isDev = process.env.NODE_ENV !== 'production';
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Content-Security-Policy', value: contentSecurityPolicy(isDev) },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
};

export default nextConfig;
