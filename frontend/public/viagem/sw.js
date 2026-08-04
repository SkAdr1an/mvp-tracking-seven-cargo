const STATIC_CACHE = 'seven-public-trip-static-v3'
const SHELL = [
  '/index.html',
  '/viagem/manifest.webmanifest',
  '/viagem/icon-placeholder.svg',
  '/viagem/icon-maskable-placeholder.svg',
]

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith('seven-public-trip-') && key !== STATIC_CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('message', (event) => {
  if (event.data?.type !== 'CACHE_STATIC_URLS' || !Array.isArray(event.data.urls)) return
  const safeUrls = event.data.urls.filter((url) =>
    typeof url === 'string' &&
    url.startsWith('/') &&
    !url.startsWith('/api/') &&
    !url.startsWith('/viagem/') &&
    !url.includes('?'),
  )
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(safeUrls)))
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.pathname.startsWith('/api/public/trips/') || url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html')))
    return
  }
  if (url.origin !== self.location.origin) return
  if (!['script', 'style', 'font', 'image'].includes(request.destination)) return
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone()
        void caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy))
      }
      return response
    })),
  )
})
