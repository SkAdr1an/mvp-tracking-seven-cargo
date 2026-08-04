import type { CachedPublicTrip, PublicTrip } from '../types'

const DATABASE = 'seven-public-trip-v2'
const STORE = 'trips'

export async function tokenCacheKey(token: string): Promise<string> {
  const bytes = new TextEncoder().encode(token)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return `trip:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: 'key' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function transaction<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await database()
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode)
      const request = operation(tx.objectStore(STORE))
      let result: T
      request.onsuccess = () => { result = request.result }
      request.onerror = () => reject(request.error)
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
      tx.oncomplete = () => resolve(result)
    })
  } finally {
    db.close()
  }
}

export async function readTripCache(token: string): Promise<CachedPublicTrip | undefined> {
  const key = await tokenCacheKey(token)
  return transaction('readonly', (store) => store.get(key)) as Promise<CachedPublicTrip | undefined>
}

export async function saveTripCache(token: string, data: PublicTrip, synchronizedAt: string): Promise<CachedPublicTrip> {
  const record = { key: await tokenCacheKey(token), data, synchronizedAt }
  await transaction('readwrite', (store) => store.put(record))
  return record
}

export async function clearTripCache(token: string): Promise<void> {
  const key = await tokenCacheKey(token)
  await transaction('readwrite', (store) => store.delete(key))
}
