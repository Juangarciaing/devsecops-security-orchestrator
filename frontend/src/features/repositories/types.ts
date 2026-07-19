export type RepositoryProvider = 'github' | 'gitlab' | 'bitbucket'

export interface CodeRepository {
  id: string
  provider: RepositoryProvider
  owner: string
  name: string
  clone_url: string
  default_branch: string
  credential_ref: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface RegisterRepositoryInput {
  provider: RepositoryProvider
  owner: string
  name: string
  clone_url: string
  default_branch: string
  credential_ref?: string
}
