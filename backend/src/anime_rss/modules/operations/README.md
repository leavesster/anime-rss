# Operations module

Owns generic durable jobs and worker leases. Business deadlines remain in their
own module; a job only invokes a public command when that deadline is due.

## Public surface

- `JobService.ensure_job`
- `JobService.claim_due`
- `JobService.complete`
- `JobService.reschedule`

## Invariants

- `(job_kind, dedupe_key)` is unique.
- Claims use a conditional update, so overlapping workers cannot both acquire
  the same unexpired lease.
- Job payloads are versioned and contain no credentials.
