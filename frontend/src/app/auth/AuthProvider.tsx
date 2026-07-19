import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useMe } from '@/features/auth/queries'
import { clearToken, getToken, setToken } from '@/shared/api/token'
import {
  AuthContext,
  type AuthContextValue,
  type AuthStatus,
} from './AuthContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [hasToken, setHasToken] = useState(() => getToken() !== null)
  const meQuery = useMe(hasToken)

  const login = useCallback((token: string) => {
    setToken(token)
    setHasToken(true)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setHasToken(false)
  }, [])

  const status: AuthStatus = !hasToken
    ? 'anon'
    : meQuery.isSuccess
      ? 'authed'
      : meQuery.isError
        ? 'anon'
        : 'loading'

  const value = useMemo<AuthContextValue>(() => {
    const currentUser = status === 'authed' ? (meQuery.data ?? null) : null
    return {
      user: currentUser,
      role: currentUser?.role ?? null,
      status,
      login,
      logout,
    }
  }, [meQuery.data, status, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
