# syntax=docker/dockerfile:1
#
# `pip-audit` SCA scanner image (Module 11 D6). Base is pinned by BOTH tag
# and digest (higher bar than the app images in this directory, which are
# tag-only) so a fresh build cannot silently drift to a newer, unaudited
# base layer. `pip-audit` itself is pinned to an exact release.
#
# No ENTRYPOINT (D6): the same image serves both the pre-flight manifest
# probe (`python -c ...`) and the real audit (`pip-audit ...`) via
# `DockerContainerRunner`'s full-argv `command` — never a shell string.

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

RUN pip install --no-cache-dir pip-audit==2.10.1

# D2: `DockerContainerRunner.run()` exposes no `environment` parameter and
# mounts the rootfs read-only, so pip-audit's cache/home must be redirected
# via image ENV — the only tmpfs mount available at runtime is `/tmp`.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/pip-audit-cache \
    PIP_NO_CACHE_DIR=1

# Cosmetic only — `DockerContainerRunner` unconditionally forces
# `--user 65532:65532` on every launched container regardless of this
# directive, but declaring it here documents intent and keeps the image
# safe to run standalone outside the orchestrator too.
USER 65532:65532

WORKDIR /
