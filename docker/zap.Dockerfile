# syntax=docker/dockerfile:1
#
# OWASP ZAP baseline DAST scanner image (dast-scanner PR5b, design "File
# Changes"/D6). Thin `FROM`, pinned by BOTH tag and digest (confirmed live,
# `docker pull ghcr.io/zaproxy/zaproxy:stable` + `docker inspect
# --format='{{index .RepoDigests 0}}'`, this apply batch — not a guessed
# hash) so a fresh checkout cannot silently drift to a newer, unaudited ZAP
# release. No rebuild step of our own: the upstream image already ships
# `zap-baseline.py` on `PATH` and needs no additional packages.
#
# No ENTRYPOINT/CMD override: `DockerContainerRunner` always launches with a
# full argv `command` (never a shell string) — `zap-baseline.py -t <url> ...`
# resolves directly off `PATH` (design D5 Interfaces section:
# `infrastructure.scanners.zap_descriptor.build_zap_argv`).
#
# Rung-3 hardening (PR4 spike, design D6): the upstream image's own `zap`
# user is uid:gid `1000:1000` with `HOME=/home/zap/` baked into its ENV —
# `zap-baseline.py` resolves its home via native `getpwuid()` and ignores
# `$HOME` overrides, so `ZapDastDockerExecution` (PR5b) MUST launch this
# image with `user="1000:1000"` (not this repo's default hardened
# `65532:65532`) plus a writable tmpfs at `/home/zap`. This file only pins
# the image; the per-call hardening override lives in
# `infrastructure.container.zap_dast_execution`.
FROM ghcr.io/zaproxy/zaproxy:stable@sha256:8d387b1a63e3425beef4846e39719f5af2a787753af2d8b6558c6257d7a577a2
