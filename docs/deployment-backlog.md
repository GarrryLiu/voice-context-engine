# Full web deployment backlog

Status: deferred. No public product deployment has been performed. The current deliverable is a persistent, single-user local web product launched with `python3 run.py`.

## Release 1: hosted full product

1. **Deployment target and budget.** Select a Docker-capable Linux platform supporting long-lived WebSockets and background workers, region, monthly infrastructure budget and model spending limit. Provision staging first. No GPU required while inference uses hosted APIs.
2. **Durable product database.** Adapt product workspace/document/proposal storage to PostgreSQL, including version fences, atomic transcript capture and map apply. Existing PostgreSQL infrastructure support does not establish parity for every product store. Add migrations and an explicit, verified SQLite import path. Store uploaded binary files in private object storage if retained. Pass restart, concurrent-write and backup/restore tests.
3. **Identity and isolation.** Add real login, user/workspace ownership and authorization on HTTP, WebSocket, documents, graphs and background jobs. The local page token is not a hosted account system. Test two users cannot read or modify each other's data.
4. **Deployment and operations.** Build app/native runtime image, HTTPS and WebSocket routing, secrets injection, readiness probes, structured redacted logs, quotas and provider timeouts. Add worker deployment only for enabled background flows; use Redis/Kafka when required by that deployment, not as prerequisites for the local demo.
5. **Release validation.** Exercise real microphone → transcript → reply → saved documents → recursive map → resume on supported desktop/mobile browsers. Verify cancellation, failures, backups, restore and migration rollback. Publish versioned image with documented rollback and operator runbook.

## Resources needed before provisioning

- Cloud account/project and deployment authorization; target region and budget.
- Managed PostgreSQL database plus automated backups and restore retention.
- HTTPS hostname (platform hostname initially acceptable).
- Provider API secret and available text/STT/TTS models, configured in the platform secret manager.
- Login provider configuration; mail delivery if email login is selected.
- Object storage only when durable audio/attachments are included.

## Local release boundary

SQLite is a real server-side database on the user's machine, not browser-only storage. It is appropriate for this single-user local version. Shipping the local launcher does not satisfy hosted multi-user isolation or cloud availability. Demo and connected databases remain separate. No private data or credentials are bundled.
