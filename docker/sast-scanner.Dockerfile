# syntax=docker/dockerfile:1
#
# `sast-scanner` AST-based SAST scanner image (Module 11 D1). Multi-stage:
# the builder stage clones the `sast-scanner` source and checks out an
# EXACT, immutable commit SHA — NOT the mutable `v1.0.0` tag name — then
# asserts the checked-out `HEAD` matches that SHA before the final stage
# copies only the `sast/` package out. `.git`/the `git` binary never reach
# the runtime image (smaller, no clone tooling at run).
#
# No ENTRYPOINT (mirrors `docker/pip-audit.Dockerfile`'s D6): the same image
# serves the real scan (`python -m sast.cli ...`) via `DockerContainerRunner`'s
# full-argv `command` — never a shell string.

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Immutable pin (D1, CORRECTED): the exact commit SHA the `v1.0.0` tag
# peels to (`git rev-list -n1 v1.0.0`) — NOT `git rev-parse v1.0.0`, which
# resolves to the annotated tag OBJECT's own SHA (a different value that
# would silently misread as a commit SHA to anyone auditing this file).
ARG SAST_SCANNER_COMMIT=2d68cbbf7fe08d61801315eb0668f07aad60ac95

WORKDIR /src
RUN git clone https://github.com/Juangarciaing/sast-scanner . \
    && git checkout "${SAST_SCANNER_COMMIT}" \
    && [ "$(git rev-parse HEAD)" = "${SAST_SCANNER_COMMIT}" ]

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

COPY --from=builder /src/sast /app/sast

# Cosmetic only — `DockerContainerRunner` unconditionally forces
# `--user 65532:65532` on every launched container regardless of this
# directive, but declaring it here documents intent and keeps the image
# safe to run standalone outside the orchestrator too.
USER 65532:65532

WORKDIR /app
