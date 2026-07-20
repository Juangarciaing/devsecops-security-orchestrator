# syntax=docker/dockerfile:1
#
# `semgrep` multi-language SAST scanner image (Module 11 D5). Single-stage,
# same digest-pinned `python:3.12-slim` base as `pip-audit.Dockerfile` (higher
# bar than the app images in this directory, which are tag-only) so a fresh
# build cannot silently drift to a newer, unaudited base layer. `semgrep`
# itself is pinned to an exact release via pip (confirmed against PyPI's
# `info.version` AND the GitHub `releases/latest` API at build-authoring
# time: both agree on `1.170.0` — the design doc's `1.90.0` guess was stale
# training-knowledge and is superseded by this live-verified value).
#
# Rulesets are fetched at BUILD time only (`curl` against the real Semgrep
# registry — `https://semgrep.dev/c/p/<pack>` confirmed reachable and to
# return valid rule YAML for all 4 packs below) and baked into `/rules`; the
# running scan container launches with `network_disabled=True` (matches
# Gitleaks/AST-SAST's hermetic pattern, NOT pip-audit's online exception) so
# `curl`'s presence in the final image is harmless at runtime — no code path
# can reach the network once the container's network is disabled. Rules
# update only on image rebuild.
#
# No ENTRYPOINT (mirrors `pip-audit.Dockerfile`/`sast-scanner.Dockerfile`'s
# convention): the same image serves the real scan
# (`semgrep scan --config /rules --json ...`) via `DockerContainerRunner`'s
# full-argv `command` — never a shell string.

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

# `curl` is NOT present in the base `python:3.12-slim` image (confirmed by
# inspection) — installed here purely to fetch rule packs at BUILD time.
# `ca-certificates` is already present in the base image but pinned
# explicitly for clarity/reproducibility.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir semgrep==1.170.0

# Build-time-only rule fetch (D3/D4): each registry pack's combined YAML is
# fetched via the real, confirmed `https://semgrep.dev/c/p/<pack>` URL shape
# into its own file under `/rules` — `semgrep scan --config /rules` loads
# every YAML file in that directory. Covers all 3 languages in this repo
# (Python backend, TypeScript frontend, Dockerfiles) plus a cross-language
# security-audit pack.
RUN mkdir -p /rules \
    && curl -sSL --fail https://semgrep.dev/c/p/security-audit -o /rules/security-audit.yml \
    && curl -sSL --fail https://semgrep.dev/c/p/python -o /rules/python.yml \
    && curl -sSL --fail https://semgrep.dev/c/p/typescript -o /rules/typescript.yml \
    && curl -sSL --fail https://semgrep.dev/c/p/dockerfile -o /rules/dockerfile.yml

# D2: `DockerContainerRunner.run()` exposes no `environment` parameter and
# mounts the rootfs read-only, so semgrep's home/cache must be redirected via
# image ENV — the only tmpfs mount available at runtime is `/tmp`.
# `SEMGREP_SEND_METRICS=off` is belt-and-suspenders (D3): the `--metrics=off
# --disable-version-check` scan flags already suppress metrics/version-check
# network attempts, but setting the env var too means Semgrep makes ZERO
# network attempts even if a future scan is ever launched without those
# flags explicitly set.
ENV HOME=/tmp \
    SEMGREP_SEND_METRICS=off

# Cosmetic only — `DockerContainerRunner` unconditionally forces
# `--user 65532:65532` on every launched container regardless of this
# directive, but declaring it here documents intent and keeps the image
# safe to run standalone outside the orchestrator too.
USER 65532:65532

WORKDIR /
