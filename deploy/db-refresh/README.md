# Monthly stations.db refresh (host-side)

The monthly UKE → `stations.db` refresh runs on the **NUC host (NUC_HOST)**, not
the forgejo CI runner. The runner (the CI runner host) cannot reach `bip.uke.gov.pl` over
its WiFi egress (connection times out), while the host reaches both UKE (~0.25s)
and the forgejo deploy server. The host runs the pipeline in a throwaway
`python:3.12-slim` container **on the host network**, then pushes the rebuilt DB
to forgejo `main` — forgejo CI deploys it on push, exactly like a manual data
commit. The validation guards (count drop > 25%, missing band, out-of-bounds
coords, duplicates, suspiciously small xlsx) abort before any commit, so a bad
UKE month fails safe.

Flow:

```
signal-scout-db-refresh.timer  ->  .service  ->  /usr/local/bin/signal-scout-db-refresh
   (host_db_refresh.sh)  ->  docker run --network host  ->  git clone
   ->  scripts/uke_refresh_pipeline.sh  (download -> validate -> rebuild
       -> validate -> commit -> push to forgejo)
```

## Install (on NUC_HOST, as root)

From this directory:

```sh
# 1) script + units
install -m 0755 host_db_refresh.sh /usr/local/bin/signal-scout-db-refresh
install -m 0644 signal-scout-db-refresh.service signal-scout-db-refresh.timer \
        /etc/systemd/system/

# 2) push token — a forgejo PAT for hcylwik with repo read+write, root-only
printf 'FORGEJO_TOKEN=%s\n' '<your-forgejo-token>' > /etc/signal-scout-db-refresh.env
chmod 600 /etc/signal-scout-db-refresh.env

# 3) enable monthly + run once now (does the overdue refresh)
systemctl daemon-reload
systemctl enable --now signal-scout-db-refresh.timer
systemctl start  signal-scout-db-refresh.service
journalctl -fu  signal-scout-db-refresh.service     # watch it
```

`systemctl list-timers signal-scout-db-refresh.timer` shows the next run
(27th of each month, 19:15, `Persistent=true` so a missed month catches up).

Overrides via the EnvironmentFile if anything moves: `FORGEJO_HOST`
(default `HOMELAB_LAN_IP:3000`), `REPO` (`hcylwik/signal-scout`), `IMAGE`.
