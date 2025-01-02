<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [GTFS Real Time](#gtfs-real-time)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->


Sign an agreement with SNCB to be able to use their data: https://www.belgiantrain.be/en/3rd-party-services/mobility-service-providers/public-data

Once you have the agreement signed by both parties, you will get a URL to a page with the datasets. Copy the adress of the GTFS realtime endpoint and add it to the .env file as SNCB_GTFS_REALTIME_API_URL.

As a fallback you can use the GTFS mirror at [https://data.gtfs.be/sncb/gtfs/tripUpdates.pb](https://data.gtfs.be/sncb/gtfs/tripUpdates.pb) provided by [GTFS.be](https://gtfs.be).