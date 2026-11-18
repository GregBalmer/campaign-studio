// Lets Chrome and Edge offer "Install Campaign Studio" as its own app window.
// It caches nothing on purpose: the app's data lives in the local server, and a
// cached interface would hide updates.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => e.respondWith(fetch(e.request)));
