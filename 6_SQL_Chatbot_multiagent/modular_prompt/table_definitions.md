# Table Definitions (High Level)

| Table                          | Purpose                                               | Key Fields                                               |
|-------------------------------|-------------------------------------------------------|----------------------------------------------------------|
| getvehicles                   | Live AVL data (5-min snapshots)                       | vid, timestamp, tablockid, blk, lat, lon, tatripid       |
| clever_pred                   | Live SOC predictions                                  | bus_id, pred_end_soc, current_soc, block_id, timestamp   |
| trip_event_bustime            | Historical trip metrics                               | vid, tatripid, start_timestamp, kWh/mi, end_soc          |
| trip_event_bustime_to_block   | Block-level rollups (historical)                      | vid, tablockid, start_timestamp                          |
| gtfs_block                    | Static block definitions                              | BLOCK_ID_GTFS, BLOCK_ID_USER, SERVICE_ID, ROUTE_ID       |
| bus_vid                       | Bus metadata & EV tags                                | name, model, battery_capacity                            |

### 1. getvehicles – Real-time Vehicle Telemetry

Live AVL data from Clever Devices (updated every 5 minutes).

| Variable     | Description                     | Relationships / Join Keys                                                 |
| ------------ | ------------------------------- | ------------------------------------------------------------------------- |
| vid        | Vehicle ID (e.g., bus number)   | Joins with bus_vid.name, clever_pred.bus_id, trip_event_bustime.vid |
| lat, lon | GPS coordinates (degrees)       | —                                                                         |
| rt         | Route ID currently being served | Joins with gtfs_block.ROUTE_ID                                          |
| tablockid  | TA’s/User’s block ID            | Joins with gtfs_block.BLOCK_ID_USER, trip_event_bustime.tablockid     |
| blk        | GTFS block ID                   | Joins with gtfs_block.BLOCK_ID_GTFS, trip_event_bustime.blk           |
| tatripid   | User-defined trip ID            | Joins with trip_event_bustime.tatripid, clever_pred.trip_id           |
| tripid     | GTFS trip ID                    | Joins with gtfs_trip.TRIP_ID                                            |
| timestamp  | Epoch timestamp (seconds)       | Aligns with clever_pred.timestamp for real-time sync                    |

---

### 2. trip_event_bustime – Historical EV Trip Metrics

Trip-level performance statistics from past service days.

| Variable           | Description                | Relationships / Join Keys                                |
| ------------------ | -------------------------- | -------------------------------------------------------- |
| vid              | Vehicle ID                 | Joins with getvehicles.vid, bus_vid.name             |
| tatripid         | Trip ID (user-defined)     | Joins with getvehicles.tatripid, clever_pred.trip_id |
| tablockid, blk | User/GTFS block IDs        | Join to gtfs_block and trip_event_bustime_to_block   |
| start_timestamp  | Actual trip start (epoch)  | Used in time-based comparisons or filtering              |
| end_soc          | Actual SOC at trip end (%) | Compared with clever_pred.pred_end_soc                 |

---

### 3. clever_pred – Real-time SOC & Range Predictions

Forecasted EV battery usage and driving metrics.

| Variable        | Description                     | Relationships / Join Keys                                      |
| --------------- | ------------------------------- | -------------------------------------------------------------- |
| bus_id        | Vehicle ID                      | Joins with getvehicles.vid, bus_vid.name                   |
| block_id      | TA/User block ID                | Joins with gtfs_block.BLOCK_ID_USER, getvehicles.tablockid |
| block_id_gtfs | GTFS block ID                   | Joins with gtfs_block.BLOCK_ID_GTFS, getvehicles.blk       |
| pred_end_soc  | Forecasted SOC at block end (%) | Validated against trip_event_bustime.end_soc                 |
| current_soc   | Telematics SOC snapshot (%)     | Live value linked to vehicle status                            |

---

### 4. gtfs_block – Static Block Schedules

Definition of fixed service blocks from GTFS.

| Variable               | Description                             | Relationships / Join Keys                                  |
| ---------------------- | --------------------------------------- | ---------------------------------------------------------- |
| BLOCK_ID_GTFS        | GTFS-standard block ID                  | Joins with getvehicles.blk, trip_event_bustime.blk     |
| BLOCK_ID_USER        | TA/User-defined block ID (same as GTFS) | Joins with getvehicles.tablockid, clever_pred.block_id |
| ROUTE_ID             | Route identifier                        | Joins with getvehicles.rt                                |
| INSERVICE_START_TIME | In-service start (HH\:MM)               | Used for in-service status validation                      |

---

### 5. bus_vid – Static Bus Metadata

Reference-only table with vehicle specifications and type.

| Variable           | Description                          | Relationships / Join Keys                              |
| ------------------ | ------------------------------------ | ------------------------------------------------------ |
| name             | Vehicle name (maps to vid)         | Joins with getvehicles.vid, trip_event_bustime.vid |
| battery_capacity | Default energy capacity (kWh)        | Used in energy efficiency calculations                 |
| model            | Vehicle model (e.g., 'EV', 'Diesel') | Used to filter electric vehicles                       |

---

### 6. trip_event_bustime_to_block – Historical Block Rollups

Daily aggregates of performance per vehicle per block.

| Variable           | Description                    | Relationships / Join Keys                     |
| ------------------ | ------------------------------ | --------------------------------------------- |
| vid              | Vehicle ID                     | Joins with getvehicles.vid, bus_vid.name  |
| tablockid, blk | User/GTFS block IDs            | Joins with gtfs_block, getvehicles        |
| start_timestamp  | Block start time (epoch)       | Temporal alignment with schedule              |
| end_soc          | Actual SOC at end of block (%) | Benchmarks against clever_pred.pred_end_soc |

### 7. gtfs_trip – Static Trip Mapping

Details of individual trips and their association with blocks, routes, and shapes.

| Variable        | Description                          | Relationships / Join Keys                                    |
| --------------- | ------------------------------------ | ------------------------------------------------------------ |
| TRIP_ID       | GTFS trip identifier                 | Joins with getvehicles.tripid, trip_event_bustime.tripid |
| BLOCK_ID_GTFS | GTFS block ID this trip belongs to   | Joins with gtfs_block.BLOCK_ID_GTFS, getvehicles.blk     |
| BLOCK_ID_USER | User-defined block ID                | Joins with getvehicles.tablockid                           |
| DAY           | Weekday name (e.g., MONDAY)          | Used in service filtering                                    |
| SERVICE_ID    | Service ID for operational day       | Joins with gtfs_calendar_dates.SERVICE_ID                  |
| SHAPE_ID      | Shape path ID                        | Joins with gtfs_shape.shape_id                             |
| START_TIME    | Trip start time (HH\:MM, 24h)        | Used in temporal filtering                                   |
| END_TIME      | Trip end time (HH\:MM, 24h)          | Used in trip duration calculations                           |
| TRIP_DISTANCE | Total miles of the trip              | Supports energy efficiency calculations                      |
| TRIP_TYPE     | STANDARD, DEADHEAD, or LAYOVER | Useful for filtering only in-service trips                   |

---

### 8. gtfs_shape – Static Route Geometry

GPS path points defining the geographic route of trips.

| Variable    | Description                                   | Relationships / Join Keys                               |
| ----------- | --------------------------------------------- | ------------------------------------------------------- |
| shape_id  | Unique shape identifier for a route segment   | Joins with gtfs_trip.SHAPE_ID, clever_pred.shape_id |
| latitude  | Latitude coordinate of the path point (°)     | Used for map plotting                                   |
| longitude | Longitude coordinate of the path point (°)    | Used for map plotting                                   |
| sequence  | Order of the point along the path             | Defines shape traversal order                           |
| distance  | Cumulative distance (meters) from shape start | Supports segment-based calculations                     |
| route_id  | Route associated with the shape (optional)    | Joins with gtfs_trip.ROUTE_ID                         |

---

### 9. gtfs_calendar_dates – Valid Service Days

Defines which service IDs are active on which dates.

| Variable     | Description                              | Relationships / Join Keys                                  |
| ------------ | ---------------------------------------- | ---------------------------------------------------------- |
| DATE       | Calendar date (YYYY-MM-DD)               | Primary key, used for filtering based on today             |
| SERVICE_ID | Operational service ID                   | Joins with gtfs_trip.SERVICE_ID, gtfs_block.SERVICE_ID |
| DAY        | Weekday of the given date (e.g., MONDAY) | Aligns with gtfs_trip.DAY and gtfs_block.DAY           |


