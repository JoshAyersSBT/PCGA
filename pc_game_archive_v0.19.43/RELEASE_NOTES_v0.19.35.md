# PCGA v0.19.35 — Jellyfin uptime and diagnostic visibility

- Enabled Jellyfin is started when its container is missing or stopped, rather than being silently skipped.
- The upgrader waits for Jellyfin's `/health` response and verifies reachability again from the portal sidecar. The portal's `PCGA_TOOL_HOST` and `PCGA_JELLYFIN_PORT` are reconciled to the current gateway and configured port. A broken connection fails the upgrade with actionable diagnostics instead of declaring success.
- Healthy Jellyfin containers are left running; no unconditional forced recreation or media/config reset occurs.
- The Media diagnostics profile always contains Jellyfin even when its Docker container is absent, with a clear missing state.
- Movies & TV connectivity errors now offer Retry and Media diagnostics instead of a raw exception alone.
- A read-only `/api/jellyfin/health` portal probe reports reachability, port, and whether an API token is configured.

**Note:** This release has offline tests but has not been run against the actual Ubuntu appliance. Jellyfin may be deliberately disabled in PCGA settings; in that case the upgrader does not start it. A missing/expired Jellyfin token can still require credential repair after the HTTP service is healthy.
