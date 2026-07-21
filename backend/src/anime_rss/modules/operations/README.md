# Operations module

Owns generic durable jobs and worker leases. Business deadlines remain in their
own module; a job only invokes a public command when that deadline is due.

## Public surface

- `JobService.ensure_job`
- `JobService.synchronize_job`
- `JobService.claim_due`
- `JobService.complete`
- `JobService.reschedule`
- `JobService.list_jobs`
- `JobService.list_runs`
- `Scheduler.run_once`

## Invariants

- `(job_kind, dedupe_key)` is unique.
- Claims use a conditional update, so overlapping workers cannot both acquire
  the same unexpired lease.
- Job payloads are versioned and contain no credentials.
- Every claimed execution has an append-only run record.
- Expired leases make interrupted runs recoverable after restart.
- Business-owned deadlines may replace a queued due time; generic periodic jobs
  retain the worker's rescheduled due time.

## Does not own

- Feed retry policy or next-fetch state
- Selection fallback deadlines
- Expected-episode and missing-state evaluation
- Download retry and reconciliation state
- Cross-module business failure state
