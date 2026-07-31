"""Fixed argv descriptor for OWASP ZAP baseline scans (dast-scanner PR5a,
tasks 5.9).

Unlike Gitleaks/pip-audit/Semgrep/AST-SAST — whose argv is fully static —
ZAP's argv has exactly one runtime-interpolated element: the validated
target URL. `build_zap_argv` is the SOLE place that interpolation happens,
and it always inserts the URL as one opaque argv element between the fixed
head and tail — never composed into a shell string (threat matrix: command
composition, dast-scanner design D5 Interfaces section).

Deliberately scoped to argv/constants only: the full invocation (dedicated
Docker network, named volume, chmod-0777 init, the two-run
baseline-then-`cat`-report split, and cleanup — design D4/D7) is
`infrastructure.container.zap_dast_execution.ZapDastDockerExecution`
(dast-scanner PR5b) — out of scope here. PR5a is pure descriptor + adapter,
no container execution.
"""

from __future__ import annotations

#: `zap-baseline.py` hardcodes its report base directory as `/zap/wrk/` — it
#: cannot be redirected via CLI flag (design D7).
_ZAP_WORK_DIR = "/zap/wrk"
_ZAP_REPORT = "report.json"

#: The validated target URL is inserted between these two fixed tuples —
#: never interpolated into a shell string.
_ZAP_ARGV_HEAD: tuple[str, ...] = ("zap-baseline.py", "-t")
_ZAP_ARGV_TAIL: tuple[str, ...] = ("-J", _ZAP_REPORT, "-I", "-s")  # -I: WARN is not a failure


def build_zap_argv(target_url: str) -> tuple[str, ...]:
    """Build the fixed `zap-baseline.py` argv, with `target_url` inserted as
    ONE opaque argv element between `_ZAP_ARGV_HEAD` and `_ZAP_ARGV_TAIL`.

    Callers MUST pass an already-validated URL (`domain.services
    .target_url_policy` + `infrastructure.security.dns_target_resolver`,
    dast-scanner PR3) — this function performs no validation of its own.
    """
    return (*_ZAP_ARGV_HEAD, target_url, *_ZAP_ARGV_TAIL)
