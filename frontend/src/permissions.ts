import { createContext, useContext } from 'react'
import type { PanelSession } from './types'

export const SessionContext = createContext<PanelSession | null>(null)
export const hasPermission = (session: PanelSession | null | undefined, permission: string) => Boolean(session?.permissions.includes(permission))
export const hasAnyPermission = (session: PanelSession | null | undefined, ...permissions: string[]) => permissions.some((permission) => hasPermission(session, permission))
export const hasAllPermissions = (session: PanelSession | null | undefined, ...permissions: string[]) => permissions.every((permission) => hasPermission(session, permission))
export function usePermission(permission: string) { return hasPermission(useContext(SessionContext), permission) }
export function usePanelSession() { return useContext(SessionContext) }
