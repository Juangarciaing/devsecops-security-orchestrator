"""Twelve-Factor application configuration.

Required settings have no default, so `Settings()` raises `pydantic.ValidationError`
immediately if a required environment variable is missing — fail fast at process
startup, before any request is served.
"""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    secret_key: str
    jwt_secret_key: str
    environment: str = "development"
    jwt_expiry_minutes: int = 30
    first_admin_email: str | None = None
    first_admin_password: str | None = None
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Module 9 — opt-in CORS for a browser-hosted frontend served from a
    # different origin (e.g. local `npm run dev` at :5173 talking to this
    # API at :8000). Comma-separated list of exact allowed origins; empty
    # (the default) adds ZERO middleware and ZERO behavior change — no
    # deployment gets CORS headers unless it explicitly opts in.
    cors_allowed_origins: str = ""

    # Module 6 — hardened scanner-container execution. Both images are
    # tag+digest-pinned (confirmed against the registry at implementation
    # time via `docker pull`/`docker inspect`) so a fresh checkout cannot
    # silently drift to a newer, unaudited image build.
    scan_container_image: str = (
        "ghcr.io/gitleaks/gitleaks:v8.30.1"
        "@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
    )
    scan_git_image: str = (
        "alpine/git:2.54.0@sha256:697cb1c85aefc5724febaec2202a974e0d66f6abb6be91a9a86d0c8757af692a"
    )
    scan_memory_limit_mb: int = 512
    scan_cpu_limit: float = 1.0
    scan_pids_limit: int = 128
    scan_timeout_seconds: int = 120

    # Module 11 — pip-audit SCA scanner image, built locally from
    # `docker/pip-audit.Dockerfile` (which itself pins its `python:3.12-slim`
    # base by digest and `pip-audit` by exact version). Tag-only here,
    # mirroring how `scan_git_image`/`scan_container_image` are configured.
    scan_pip_audit_image: str = "pip-audit-scanner:local"

    # Module 11 — AST-based SAST scanner image, built locally from
    # `docker/sast-scanner.Dockerfile` (which pins its `python:3.12-slim`
    # base by digest and the `sast-scanner` source by exact commit SHA).
    # Tag-only here, mirroring `scan_pip_audit_image`.
    scan_sast_image: str = "sast-scanner:local"

    # Module 11 — Semgrep multi-language SAST scanner image, built locally
    # from `docker/semgrep.Dockerfile` (which pins its `python:3.12-slim`
    # base by digest, `semgrep` by exact version, and its rule packs at
    # build time). Tag-only here, mirroring `scan_sast_image`.
    scan_semgrep_image: str = "semgrep-scanner:local"

    # dast-scanner PR5b — OWASP ZAP baseline DAST scanner image, built
    # locally from `docker/zap.Dockerfile` (a thin `FROM`, digest-pinned to
    # the upstream `ghcr.io/zaproxy/zaproxy:stable` image — no local
    # modification). Tag-only here, mirroring `scan_semgrep_image`/
    # `scan_pip_audit_image`.
    scan_zap_image: str = "zap-scanner:local"
    # Name of the dedicated, non-default Docker bridge network every ZAP
    # scan container joins (design D4) — never the compose default bridge,
    # so it cannot reach `postgres`/`redis`/`api` by service name or bridge
    # IP even if URL/DNS validation is bypassed.
    dast_network_name: str = "dast-scan-net"
    # ZAP baseline scans (spider + passive) can run materially longer than
    # this repo's other scanners against an arbitrary external target;
    # kept as its own knob rather than overloading `scan_timeout_seconds`.
    dast_timeout_seconds: int = 300
    # dast-scanner PR6 (design D9): deny-by-default (Non-Goals: "Target
    # ownership verification is explicitly out of scope"). Mirrors
    # `credential_encryption_key`'s fail-closed precedent exactly — a fresh
    # deployment boots with DAST triggering rejected until an operator
    # explicitly opts in. Checked both at the API gate (`POST
    # /targets/{id}/scans` -> 403) and, in a later PR, at the worker gate.
    dast_enabled: bool = False

    # Module 10 — HMAC-SHA256 secret for verifying inbound GitHub webhook
    # deliveries. Nullable/fail-closed (D1): the app boots without it; the
    # signature verifier treats an unset secret as always-invalid, so every
    # delivery is 401-audited rather than accepted unverified.
    github_webhook_secret: str | None = None

    # Module 13a — OpenTelemetry distributed tracing. Opt-in via presence
    # (D1): an empty (the default) endpoint means tracing is fully off — no
    # TracerProvider is set, no exporter/thread/socket is created, and the
    # existing request/task pipeline is byte-for-byte unchanged. Mirrors the
    # `cors_allowed_origins`/`github_webhook_secret` opt-in-via-presence
    # precedent; neither field is required, so tracing can never block
    # application startup.
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "orchestrator"

    # Module 13c PR8 — explicit scan-execution backend selection (spec's
    # "Explicit Backend Selection and Compatibility"). Absent/default
    # ("docker", D1) requires zero Kubernetes config and leaves the existing
    # Docker path byte-for-byte unchanged. Selecting "kubernetes" without a
    # complete `kubernetes_namespace`/`kubernetes_storage_class_name` pair
    # fails HERE, at `Settings()` construction — the earliest possible
    # startup boundary, matching this class's existing fail-fast precedent
    # for `database_url`/`redis_url`/etc — rather than deferring to a later,
    # partially-started process. This does not by itself prove the cluster
    # is reachable/valid (that is `kubernetes_preflight`'s job, run against a
    # `ClusterCapabilityPort` at worker-startup time); it only proves the
    # *shape* of the selected configuration is complete.
    scan_execution_backend: Literal["docker", "kubernetes"] = "docker"
    kubernetes_namespace: str | None = None
    kubernetes_storage_class_name: str | None = None

    # secrets-manager PR1 — separate from `secret_key` by design decision
    # (proposal: reuse would force an HKDF step or break every existing
    # `.env`). Nullable + fail-closed (D2): absent boots unchanged, a
    # deployment scans public repos with zero behavior change; storing or
    # decrypting a credential without this key raises a clear application
    # error (`CredentialSealError`/`CredentialUnsealError`) rather than
    # persisting plaintext or crashing at startup. Only its *shape* — a
    # urlsafe-base64 encoding of exactly 32 raw bytes, matching
    # `Fernet.generate_key()` — is validated here; that a caller ever
    # configures it is optional.
    credential_encryption_key: str | None = None

    # realtime-push PR1 (design D-Gate): deny-by-default, mirroring
    # `dast_enabled`'s fail-closed precedent exactly. A fresh deployment
    # boots with the relay never started (`_lifespan` no-op), the worker's
    # `publish_scan_status` returning on line 1 with zero I/O, and the SSE
    # route registered but gated to 503 before any auth/DB work — byte-
    # identical to today's polling-only behavior until explicitly enabled.
    realtime_enabled: bool = False

    @model_validator(mode="after")
    def _require_complete_kubernetes_config_when_selected(self) -> Settings:
        if self.scan_execution_backend == "kubernetes" and (
            not self.kubernetes_namespace or not self.kubernetes_storage_class_name
        ):
            raise ValueError(
                "scan_execution_backend='kubernetes' requires both "
                "kubernetes_namespace and kubernetes_storage_class_name to be set"
            )
        return self

    @model_validator(mode="after")
    def _validate_credential_encryption_key_shape(self) -> Settings:
        if self.credential_encryption_key is None:
            return self
        try:
            decoded = base64.urlsafe_b64decode(self.credential_encryption_key)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "credential_encryption_key must be a urlsafe-base64 32-byte "
                "key (e.g. cryptography.fernet.Fernet.generate_key())"
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                "credential_encryption_key must be a urlsafe-base64 32-byte "
                "key (e.g. cryptography.fernet.Fernet.generate_key())"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
