// Force-clear old PWA caches and unregister service worker.
// This file is intentionally self-destructing so iOS Safari always loads fresh assets.
const CACHE_NAME = 'pcr-disabled';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys.map((key) => caches.delete(key)));
    }).then(() => {
      return self.registration.unregister();
    }).then(() => {
      return self.clients.matchAll({ type: 'window' });
    }).then((clients) => {
      clients.forEach((client) => client.navigate(client.url));
    })
  );
});

self.addEventListener('fetch', (event) => {
  // Do not intercept anything; let the browser fetch fresh files.
});
