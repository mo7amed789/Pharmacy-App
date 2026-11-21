// Pharmacy Enterprise — mobile PWA service worker.
// Caches ONLY the app shell: the landing page, the ZXing bundle,
// the manifest and the icons. API responses (/api/*) are NEVER
// cached and NEVER served from cache — invoice and stock data must
// always go to the network, or the phone would sell from stale
// stock. If registration fails (plain HTTP on a LAN IP is not a
// secure context) the page keeps working exactly as before — the
// service worker is an install/offline-shell bonus, not a
// requirement. Install works over HTTPS (port 8443).
//
// v6.16: the cache name carries the app version and the shell is
// NETWORK-FIRST. The old cache-first handler pinned the phone to
// whatever page version was cached at the first HTTPS visit — app
// updates never reached the phone UI, so the phone kept running an
// old client against a new server. Now every load asks the server
// first and falls back to the cache only when the PC is unreachable.
var CACHE = 'pharmacy-mobile-v629';
var SHELL = ['/', '/zxing.min.js', '/manifest.json',
             '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE)
      .then(function (c) { return c.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
      .catch(function () { /* shell caching is best-effort */ })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);
  // v6.26: NEVER intercept cross-origin traffic — cloud mode talks
  // directly to Supabase; those requests must reach the network
  // untouched and must never get the cached shell as a fallback.
  if (url.origin !== self.location.origin) return;
  // NEVER intercept API traffic — always the live network.
  if (url.pathname.indexOf('/api/') === 0) return;
  if (e.request.method !== 'GET') return;
  // Network-first: try the live server, refresh the cached copy, and
  // only when the PC is unreachable fall back to the cached shell.
  e.respondWith(
    fetch(e.request).then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(e.request, { ignoreSearch: true })
        .then(function (hit) { return hit || caches.match('/'); });
    })
  );
});
