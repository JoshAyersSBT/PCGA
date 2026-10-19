# Acceptance checklist — v0.19.32

- [ ] Upgrade from an installed v0.19.31 appliance using `sudo ./upgrade.sh` with no active optical jobs.
- [ ] Portal API `/api/status` returns `0.19.32` after installation.
- [ ] In Jellyfin, a movie containing a recognized `behind the scenes` folder shows its making-of in Movies & TV → movie details → Bonus features.
- [ ] Selecting a bonus item shows the correct name and starts playback **only after pressing Play**.
- [ ] Extras preserve audio/subtitle controls and can resume or start when selected; exit restores focus to that same extra.
- [ ] TV remote Back does not leave the Movies & TV browser unexpectedly; scroll works at 960×540, 720p, 1080p and 4K.
- [ ] A movie with no extras clearly says no bonus features instead of inventing some.
- [ ] Where one Jellyfin endpoint fails, available extras still load from the other.
- [ ] Extras playback never automatically starts the next TV episode.
- [ ] Series-associated bonus features show on series details; season episodes remain navigable.
- [ ] Still-misclassified or Manual Review bonus titles remain **unassociated** until corrected (not automatically attached by title similarity).
- [ ] Jellyfin playback, NAS, optical ingest, Steam, emulators, and music continue functioning normally.
