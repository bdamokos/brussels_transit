# Le TEC

Le TEC publishes open static and realtime public transport data through the
Belgian Mobility Open Data Portal.

The provider uses Belgian Mobility APIM by default:

- Static GTFS: `/api/gtfs/feed/tec/static`
- GTFS-RT trip updates: `/api/gtfs/feed/tec/rt/trip-update`
- GTFS-RT service alerts: `/api/gtfs/feed/tec/rt/alert`

The local provider ID is `letec`. The Belgian Mobility APIM feed slug remains
`tec`, so endpoint overrides keep the `LETEC_` prefix while default URLs contain
`/tec/`.

Set `MOBILITY_API_PRIMARY_KEY` or `MOBILITY_API_SECONDARY_KEY` in `.env`. The
app sends the key as both `Ocp-Apim-Subscription-Key` and `bmc-partner-key` for
compatibility with Belgian Mobility APIM products.

Belgian Mobility GTFS-RT IDs are normalized before joining to static GTFS:

- `gs:tec:*` stop IDs map to static `stop_id`
- `gr:tec:*` route IDs map to static `route_id`
- `gt:tec:*` trip IDs map to static `trip_id`

Le TEC trip updates may provide stop-level delays without absolute event times.
When that happens, the provider combines the GTFS-RT delay with the static
`stop_times.txt` schedule for the matching trip/stop/sequence.

Static GTFS falls back to the official HTTPS Le TEC static ZIP when APIM static
GTFS is unavailable. Realtime fallbacks are not configured; the legacy Le TEC
realtime APIs are not wired into this app.

NeTEx data is available in the Belgian Mobility ecosystem, but this provider
does not consume NeTEx yet because the app's realtime display and stop explorer
are GTFS/GTFS-RT based.
