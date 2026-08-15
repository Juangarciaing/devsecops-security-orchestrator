// Mirrors the backend's `WebhookOutcome` StrEnum
// (domain/value_objects/enums.py) exactly.
export type WebhookOutcome =
  | 'accepted'
  | 'duplicate'
  | 'rejected_signature'
  | 'ignored_event'
  | 'invalid_payload'
  | 'ignored_unknown_repo'
  | 'ignored_inactive_repo'
  | 'ignored_non_default_branch'

// Mirrors the backend's `WebhookDeliveryRead` DTO exactly (design D8/D9).
// `source_ip` is present because this route is `require_role(ADMIN)`-gated,
// not just `get_current_user` — never render this type behind a non-admin
// route.
export interface WebhookDelivery {
  id: string
  signature_valid: boolean
  outcome: WebhookOutcome
  received_at: string
  delivery_id: string | null
  event_type: string | null
  source_ip: string | null
  repository_full_name: string | null
  ref: string | null
  commit_sha: string | null
}

export interface WebhookDeliveryFilters {
  limit?: number
  offset?: number
}
