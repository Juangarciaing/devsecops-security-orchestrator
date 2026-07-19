import { createContext } from 'react'
import type { CurrentUser, UserRole } from '@/features/auth/types'

export type AuthStatus = 'loading' | 'authed' | 'anon'

export interface AuthContextValue {
  user: CurrentUser | null
  role: UserRole | null
  status: AuthStatus
  login: (token: string) => void
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
)
