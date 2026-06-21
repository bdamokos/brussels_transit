<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [GTFS Real Time](#gtfs-real-time)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->


SNCB/NMBS now directs public timetable users to Belgian Mobility: https://www.belgiantrain.be/en/3rd-party-services/mobility-service-providers/public-data

The provider uses Belgian Mobility APIM by default:

- Static GTFS: `/api/gtfs/feed/nmbssncb/static`
- Realtime trip updates: `/api/gtfs/feed/nmbssncb/rt/trip-update`

Set `MOBILITY_API_PRIMARY_KEY` or `MOBILITY_API_SECONDARY_KEY` in `.env`. The app sends the key as both `Ocp-Apim-Subscription-Key` and `bmc-partner-key` for Belgian Mobility APIM compatibility.

The old SNCB GTFS-RT URL can still be used only by setting `SNCB_REALTIME_SOURCE=legacy` and `SNCB_LEGACY_GTFS_REALTIME_API_URL`. GTFS.be remains useful for static GTFS fallback through Mobility Database, but its `tripUpdates.pb` mirror is not used because it is not reliably live.
