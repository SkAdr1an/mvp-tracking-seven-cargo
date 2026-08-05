import { latLngBounds, type LatLngExpression, type PointExpression } from 'leaflet'
import { useCallback, useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'

export type MapCameraCommand =
  | { id: number; mode: 'fit' }
  | { id: number; mode: 'focus'; point: [number, number] }

function viewportPadding(container: HTMLElement): {
  paddingTopLeft: PointExpression
  paddingBottomRight: PointExpression
} {
  const width = container.clientWidth
  const mapRect = container.getBoundingClientRect()
  const openSidebar = document.querySelector<HTMLElement>('.sidebar.sidebar--open')
  const sidebarRect = openSidebar?.getBoundingClientRect()
  const sidebarOverlap = sidebarRect
    ? Math.max(0, Math.min(mapRect.right, sidebarRect.right) - Math.max(mapRect.left, sidebarRect.left))
    : 0
  const horizontal = width < 600 ? 24 : width < 1000 ? 32 : 40
  const top = width < 600 ? 82 : 68
  const bottom = width < 600 ? 88 : 76
  return {
    paddingTopLeft: [horizontal + sidebarOverlap, top],
    paddingBottomRight: [horizontal, bottom],
  }
}

export function MapResizeController({
  points,
  command,
}: {
  points: LatLngExpression[]
  command: MapCameraCommand
}) {
  const map = useMap()
  const pointsRef = useRef(points)
  const initialFitDone = useRef(false)
  pointsRef.current = points

  const fitVisiblePoints = useCallback(() => {
    const currentPoints = pointsRef.current
    if (!currentPoints.length) return
    const bounds = latLngBounds(currentPoints)
    if (!bounds.isValid()) return
    if (currentPoints.length === 1) {
      map.setView(bounds.getCenter(), 12, { animate: false })
      return
    }
    map.fitBounds(bounds, {
      ...viewportPadding(map.getContainer()),
      animate: false,
      maxZoom: 12,
    })
  }, [map])

  useEffect(() => {
    if (initialFitDone.current || !points.length) return
    initialFitDone.current = true
    fitVisiblePoints()
  }, [fitVisiblePoints, points.length])

  useEffect(() => {
    if (command.id === 0) return
    if (command.mode === 'focus') {
      map.setView(command.point, 12, { animate: false })
      return
    }
    fitVisiblePoints()
  }, [command, fitVisiblePoints, map])

  useEffect(() => {
    const container = map.getContainer()
    let frame = 0
    const refresh = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        map.invalidateSize({ pan: false })
      })
    }
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(refresh)
    observer?.observe(container)
    const layoutObserver = typeof MutationObserver === 'undefined'
      ? null
      : new MutationObserver(refresh)
    const sidebar = document.querySelector('.sidebar')
    if (sidebar) {
      layoutObserver?.observe(sidebar, { attributes: true, attributeFilter: ['class', 'style'] })
      observer?.observe(sidebar)
    }
    window.addEventListener('orientationchange', refresh)
    window.addEventListener('resize', refresh)
    refresh()
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      layoutObserver?.disconnect()
      window.removeEventListener('orientationchange', refresh)
      window.removeEventListener('resize', refresh)
    }
  }, [map])

  return null
}
