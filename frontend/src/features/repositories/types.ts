export type RepositoryProvider = 'github' | 'gitlab' | 'bitbucket'

// Mirrors the backend `CredentialKind` discriminator (secrets-manager D6).
// Only `personal_access_token` exists today.
export type CredentialKind = 'personal_access_token'

export interface CodeRepository {
  id: string
  provider: RepositoryProvider
  owner: string
  name: string
  clone_url: string
  default_branch: string
  // Read-only: the backend never returns the credential value or its
  // ciphertext (write-only credential semantics). `has_credential` and
  // `credential_kind` are the only credential-related fields on a read.
  has_credential: boolean
  credential_kind: CredentialKind | null
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
  // Write-only: the raw credential value, sealed server-side before
  // persistence. Never present on a read response.
  credential?: string | null
}
