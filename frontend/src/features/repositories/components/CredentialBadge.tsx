import { Badge } from '@/shared/ui/badge'
import type { CredentialKind } from '../types'

// Mirrors the backend `CredentialKind` discriminator (secrets-manager D6).
const CREDENTIAL_KIND_LABELS: Record<CredentialKind, string> = {
  personal_access_token: 'Personal access token',
}

// Display-only (Req: repository-management — no clear/delete-credential
// action offered here; the backend never returns the credential value or
// its ciphertext, so this badge only ever reflects presence/kind).
export function CredentialBadge({
  hasCredential,
  credentialKind,
}: {
  hasCredential: boolean
  credentialKind: CredentialKind | null
}) {
  if (!hasCredential) {
    return (
      <Badge variant="outline" data-credential="absent">
        No credential
      </Badge>
    )
  }

  return (
    <Badge variant="outline" data-credential="present">
      {credentialKind
        ? CREDENTIAL_KIND_LABELS[credentialKind]
        : 'Credential configured'}
    </Badge>
  )
}
