// Offline support: always try the network first, fall back to the last saved copy.
const CACHE = "job-brief-v1";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return; // chat requests pass straight through
  const key = url.pathname; // ignore ?t= cache-busters so jobs.json has one saved copy
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
      return res;
    }).catch(() => caches.match(key).then(r => r || caches.match(url.pathname.replace(/[^/]*$/, ""))))
  );
});
