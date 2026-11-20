// Pharmacy Enterprise — mobile PWA service worker (v6.2).
// Caches ONLY the app shell: the landing page, the ZXing bundle,
// the manifest and the icons. API responses (/api/*) are NEVER
// cached and NEVER served from cache — invoice and stock data must
// always go to the network, or the phone would sell from stale
// stock. If registration fails (plain HTTP on a LAN IP is not a
// secure context) the page keeps working exactly as before — the
// service worker is an install/offline-shell bonus, not a
// requirement. Install works over HTTPS (port 8443).
var CACHE = 'pharmacy-mobile-v1';
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
  // NEVER intercept API traffic — always the live network.
  if (url.pathname.indexOf('/api/') === 0) return;
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then(function (hit) {
      if (hit) return hit;
      return fetch(e.request).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        }
        return res;
      }).catch(function () {
        // offline and not in cache: fall back to the cached shell
        return caches.match('/');
      });
    })
  );
});
