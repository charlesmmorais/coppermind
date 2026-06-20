"""Verification engine: pre-write checks and explainable rule reports.

Verification is part of the happy path, not an optional final step. The
transaction manager runs `verify()` before every commit; violations at ERROR
severity block the commit (rollback), while WARNING/ADVISORY are surfaced but
do not block.
"""

from coppermind.verification.checks import Severity, Violation, verify

__all__ = ["Severity", "Violation", "verify"]
