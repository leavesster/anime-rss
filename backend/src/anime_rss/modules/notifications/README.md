# Notifications module

Owns in-application notification facts and external delivery attempts. It
consumes integration events and never participates in selection decisions.

## Public surface

- `NotificationService.handle_event`
- `NotificationService.list_notifications`
- `NotificationService.process_deliveries`
- `NotificationService.configure`

## Invariants

- One notification is created per source event.
- Webhook credentials are encrypted and never returned by the API.
- Delivery is idempotent by notification ID and uses bounded retry.
- A delivery failure cannot roll back or alter the originating business action.
- `EpisodeMissing.v1` is presented once per expected-episode source event.
