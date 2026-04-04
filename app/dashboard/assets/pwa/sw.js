// ─── IBKR Options Analyzer — Service Worker ────────────────────────────────
// Increment CACHE_VERSION on each deploy to bust caches and force updates.
const CACHE_VERSION = 'v1';
const STATIC_CACHE = `ibkr-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `ibkr-dynamic-${CACHE_VERSION}`;

// App shell: pre-cached on install
const APP_SHELL = [
  '/dashboard/',
  '/dashboard/assets/pwa/offline.html',
];

// ─── Install ─────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  console.log('[SW] Install');
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      console.log('[SW] Pre-caching app shell');
      return cache.addAll(APP_SHELL);
    })
  );
  self.skipWaiting();
});

// ─── Activate ────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  console.log('[SW] Activate');
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((n) => n !== STATIC_CACHE && n !== DYNAMIC_CACHE)
          .map((n) => {
            console.log('[SW] Deleting old cache:', n);
            return caches.delete(n);
          })
      )
    )
  );
  self.clients.claim();
});

// ─── Fetch ───────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle GET requests from same origin
  if (request.method !== 'GET' || url.origin !== location.origin) return;

  const path = url.pathname;

  // ── Network-only: Dash callbacks and API endpoints (must be fresh) ──
  if (
    path.includes('/_dash-update-component') ||
    path.includes('/_dash-layout') ||
    path.startsWith('/api/')
  ) {
    return; // Let the browser handle normally — no caching
  }

  // ── Cache-first: Dash component bundles (content-hashed, safe to cache) ──
  if (
    path.includes('/_dash-component-suites/') ||
    path.includes('/_dash-assets/') ||
    path.match(/\.(css|js|woff2?|ttf|eot)$/i)
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── Cache-first: static images and icons ──
  if (path.match(/\.(png|jpg|jpeg|svg|gif|ico|webp)$/i)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── Network-first: HTML navigation (the main Dash page) ──
  if (request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(networkFirst(request));
    return;
  }
});

// ─── Strategy: Cache-First ───────────────────────────────────────────────────
// Use for immutable static assets (hashed bundles, fonts, images).
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('', { status: 503, statusText: 'Offline' });
  }
}

// ─── Strategy: Network-First ─────────────────────────────────────────────────
// Use for HTML pages — prefer fresh, fall back to cache, then offline page.
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return caches.match('/dashboard/assets/pwa/offline.html');
  }
}
