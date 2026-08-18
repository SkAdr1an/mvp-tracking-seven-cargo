import type { Driver, RoutePaths } from './types'

function currentTripKey(driver: Driver): string | undefined {
  if (driver.operational?.trip_key) return driver.operational.trip_key
  if (!driver.trip_id) return undefined
  return driver.trip_id.startsWith('trafegus:') ? driver.trip_id : `trafegus:${driver.trip_id}`
}

/** Only confirmed deviations belonging to the current Trafegus trips count as off-route. */
export function currentDeviationDriverIds(drivers: Driver[], paths?: RoutePaths): Set<string> {
  const activeTripKeys = new Set(
    (paths?.paths || [])
      .filter((path) => path.deviation?.status === 'ACTIVE')
      .map((path) => path.trip_key),
  )
  return new Set(
    drivers
      .filter((driver) => {
        const tripKey = currentTripKey(driver)
        return tripKey != null && activeTripKeys.has(tripKey)
      })
      .map((driver) => driver.id),
  )
}

