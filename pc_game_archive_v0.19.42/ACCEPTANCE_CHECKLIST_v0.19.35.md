# PCGA v0.19.35 Jellyfin acceptance checklist

1. Stop active optical rips before upgrading. Run `sudo ./upgrade.sh` from the extracted v0.19.35 archive.
2. Inspect `sudo docker ps -a --filter name=jellyfin`: the `jellyfin` container should exist and be running if Movies & TV is enabled.
3. Inspect the host readiness endpoint: `curl -i --max-time 5 http://127.0.0.1:8096/health` (replace 8096 if your `.env` specifies `JELLYFIN_PORT`). Expected 2xx.
4. Inspect the portal-side readiness endpoint: `curl -sS http://127.0.0.1:8098/api/jellyfin/health`. Expected `reachable: true`; if `token_configured: false`, repair the Jellyfin API credential separately.
5. Open Control Center → Diagnostics → Media pipeline. Jellyfin should be present regardless of whether it is healthy, stopped, or missing. Read its logs if playback fails.
6. Open Movies & TV. On an error, use **Retry** after recovery or **Media diagnostics** for the service logs.
7. Verify a playable movie and a bonus feature. The upgrade should not change Jellyfin's media directories, watched status, or user accounts.
8. If Jellyfin still fails, collect `sudo docker logs --tail 150 jellyfin`, `sudo docker inspect jellyfin --format '{{.State.Status}}'`, and the `/api/jellyfin/health` output. Do not post API tokens/passwords.

No live appliance check was possible during release packaging.
