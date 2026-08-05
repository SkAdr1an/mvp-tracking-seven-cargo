export function preparePublicTripPwa(): void {
  document.title = 'Seven Cargo | Portal da Viagem'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#f3c623')
  document.querySelector('meta[name="description"]')?.setAttribute('content', 'Acompanhamento da viagem Seven Cargo')
  if (!document.querySelector('link[rel="manifest"]')) {
    const manifest = document.createElement('link')
    manifest.rel = 'manifest'
    manifest.href = '/viagem/manifest.webmanifest'
    document.head.append(manifest)
  }
  if (!('serviceWorker' in navigator) || !import.meta.env.PROD) return
  void navigator.serviceWorker.register('/viagem/sw.js', {
    scope: '/viagem/',
    updateViaCache: 'none',
  }).then(async (registration) => {
    await registration.update()
    const ready = await navigator.serviceWorker.ready
    const worker = registration.active || ready.active
    const urls = performance.getEntriesByType('resource')
      .map((entry) => new URL(entry.name))
      .filter((url) => url.origin === location.origin && !url.pathname.startsWith('/api/') && !url.pathname.includes(location.pathname))
      .map((url) => url.pathname)
    worker?.postMessage({ type: 'CACHE_STATIC_URLS', urls: [...new Set(urls)] })
  }).catch(() => {
    // Offline data still works through IndexedDB when service workers are unavailable.
  })
}
