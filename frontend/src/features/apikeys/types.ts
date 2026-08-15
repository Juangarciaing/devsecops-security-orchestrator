/** Mirrors the backend's `ApiKeyRead` DTO (never carries `hashed_key`). */
export interface ApiKey {
  id: string
  user_id: string
  key_prefix: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

/**
 * The ONLY response shape carrying the plaintext `raw_key` — returned once at
 * issuance and never persisted server-side. See design D7: the frontend must
 * hold `raw_key` in local component state only, never in the query cache,
 * `sessionStorage`, or the URL.
 */
export interface ApiKeyCreatedResponse {
  api_key: ApiKey
  raw_key: string
}
