const CACHE_NAME = 'pcr-v1';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(keys.map((key) => {
                if (key !== CACHE_NAME) return caches.delete(key);
            }));
        }).then(() => self.clients.claim())
    );
});

// Network-only for navigation and static files; we just need the SW alive for push.
self.addEventListener('fetch', (event) => {
    event.respondWith(fetch(event.request));
});

self.addEventListener('push', (event) => {
    let data = { title: 'PCR', body: 'New message', url: '/chat' };
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {}
    }
    event.waitUntil(
        self.registration.showNotification(data.title || 'PCR', {
            body: data.body || 'New message',
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/icon-192.png',
            tag: 'pcr-message',
            data: { url: data.url || '/chat' }
        })
    );
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            const url = event.notification.data && event.notification.data.url ? event.notification.data.url : '/chat';
            for (const client of clientList) {
                if (client.url === url && 'focus' in client) {
                    return client.focus();
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(url);
            }
        })
    );
});
