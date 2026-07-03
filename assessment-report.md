# Refactoring Assessment Report

Date: 2026-07-03

Repository: estimator

---

## Issue 1

Severity: Medium

Root cause: `_check_moderation` in [app/guardrails/input.py](app/guardrails/input.py) caught all exceptions from the OpenAI Moderation API call and logged them at `warning` level under a generic `moderation_call_failed` event, then silently allowed the request through (fail-open). This made moderation outages indistinguishable from routine warnings in logs/alerts.

Impact: Moderation — the guardrail meant to block hate/violence/sexual content — silently disables itself on any upstream error (timeout, bad key, outage), with no way to alert on it separately from other warning-level noise.

Fix: Raised the log level to `error` and renamed the event to `moderation_call_failed_failing_open`, making the fail-open path greppable/alertable. No control-flow change — fail-open behavior itself is preserved as-is (a deliberate tradeoff, not part of this fix's scope).

Tradeoffs: Fail-open vs. fail-closed policy was intentionally left unchanged; flipping to fail-closed would turn an OpenAI outage into a full outage of `/estimate*` endpoints and was out of scope for this fix.

Validation: Added `test_moderation_network_failure_logs_error_event` (asserts event name + level via `structlog.testing.capture_logs()`). Full `tests/test_guardrails_input.py` suite passed (14/14). Confirmed via `git stash` that 2 unrelated pre-existing failures in `tests/test_llm_wrapper.py` (litellm/openai version drift in test venv) exist on `main` too, unaffected by this change. Reviewed by Senior Audit Code Reviewer — ✅ Ready to merge, no blocking issues.
