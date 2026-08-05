import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

const publicTripMatch = window.location.pathname.match(/^\/viagem\/([A-Za-z0-9_-]{43,128})\/?$/)
const root = createRoot(document.getElementById('root')!)

if (publicTripMatch) {
  const [{ PublicTripApp }, { preparePublicTripPwa }] = await Promise.all([
    import('./public/PublicTripApp'),
    import('./public/registerServiceWorker'),
    import('leaflet/dist/leaflet.css'),
    import('./public/public-trip.css'),
  ])
  preparePublicTripPwa()
  root.render(<PublicTripApp token={publicTripMatch[1]} />)
} else if (window.location.pathname.startsWith('/viagem/')) {
  const [{ InvalidPublicTrip }, { preparePublicTripPwa }] = await Promise.all([
    import('./public/PublicTripApp'),
    import('./public/registerServiceWorker'),
    import('./public/public-trip.css'),
  ])
  preparePublicTripPwa()
  root.render(<InvalidPublicTrip />)
} else {
  const [{ QueryClient, QueryClientProvider }, { default: App }] = await Promise.all([
    import('@tanstack/react-query'),
    import('./App'),
    import('leaflet/dist/leaflet.css'),
    import('./styles.css'),
    import('./mobile-responsive.css'),
  ])
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
    },
  })
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  )
}
