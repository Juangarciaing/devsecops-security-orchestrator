import type { UserRole } from '@/features/auth/types'

export interface AdminUser {
  id: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CreateUserInput {
  email: string
  password: string
  role?: UserRole
}
