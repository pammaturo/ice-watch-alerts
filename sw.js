// Minimal service worker so phones offer "Install app". It never caches
// data.json or ledger.json, so the app always shows the latest Ices.
const SHELL = 'icewatch-shell-v1';
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['./', 'icon-192.png'])).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  // Network first; fall back to the saved page only when offline.
  e.respondWith(fetch(req).catch(() => caches.match(req).then((r) => r || caches.match('./'))));
});
