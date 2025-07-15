# Join Keys & Relationships

## Key Identifiers
- vid = getvehicles.vid = bus_vid.name = clever_pred.bus_id
- tablockid = gtfs_block.BLOCK_ID_USER = clever_pred.block_id
- blk = gtfs_block.BLOCK_ID_GTFS = trip_event_bustime.blk
- tatripid = trip_event_bustime.tatripid = getvehicles.tatripid

## Temporal Joins
- getvehicles.timestamp → trip_event_bustime.start_timestamp (approx match)
- clever_pred.timestamp → getvehicles.timestamp (within 2 minutes)

Always try to use known join keys when combining tables:

getvehicles.vid ↔ bus_vid.name, clever_pred.bus_id, trip_event_bustime.vid

getvehicles.tablockid ↔ gtfs_block.block_id_user

getvehicles.blk ↔ gtfs_block.block_id_gtfs

clever_pred.trip_id ↔ gtfs_trip.trip_id

gtfs_trip.shape_id ↔ gtfs_shape.shape_id

gtfs_trip.service_id ↔ gtfs_calendar_dates.service_id

trip_event_bustime_to_block.tablockid ↔ gtfs_block.block_id_user

trip_event_bustime_to_block.vid ↔ getvehicles.vid

### 🧩 Primary Join Keys

| Join Key            | Tables Involved                                                                                              | Description                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| `vid`               | `getvehicles`, `bus_vid`, `clever_pred`, `trip_event_bustime`, `trip_event_bustime_to_block`                 | Unique vehicle ID (e.g., bus number)       |
| `tablockid`         | `getvehicles`, `gtfs_block`, `gtfs_trip`, `clever_pred`, `trip_event_bustime`, `trip_event_bustime_to_block` | User-defined block ID                      |
| `blk`               | `getvehicles`, `gtfs_block`, `clever_pred`, `trip_event_bustime`, `trip_event_bustime_to_block`              | GTFS block ID                              |
| `tripid`            | `getvehicles`, `gtfs_trip`, `clever_pred`, `trip_event_bustime`                                              | GTFS trip ID                               |
| `tatripid`          | `getvehicles`, `clever_pred`, `trip_event_bustime`                                                           | Internal trip ID used by TA                |
| `oid` / `driver_id` | `getvehicles`, `trip_event_bustime`, `trip_event_bustime_to_block`                                           | Operator ID                                |
| `SERVICE_ID`        | `gtfs_trip`, `gtfs_block`, `gtfs_calendar_dates`                                                             | Service schedule ID per day                |
| `shape_id`          | `gtfs_trip`, `gtfs_shape`, `clever_pred`                                                                     | Shape path of the route                    |
| `ROUTE_ID`          | `gtfs_block`, `gtfs_trip`, `clever_pred`, `getvehicles`, `trip_event_bustime`                                | Route being served                         |
| `timestamp`         | `getvehicles`, `clever_pred`, `trip_event_bustime`, `trip_event_bustime_to_block`                            | Time-based matching of events              |
| `stsd`              | `getvehicles`, `trip_event_bustime`, `trip_event_bustime_to_block`                                           | Scheduled service date                     |
| `BLOCK_ID_GTFS`     | `gtfs_block`, `gtfs_trip`, `getvehicles`, `clever_pred`, `trip_event_bustime`, `trip_event_bustime_to_block` | GTFS-defined block ID                      |
| `BLOCK_ID_USER`     | `gtfs_block`, `gtfs_trip`, `getvehicles`, `clever_pred`, `trip_event_bustime`, `trip_event_bustime_to_block` | Usually same as `tablockid`                |
| `TRIP_ID`           | `gtfs_trip`, `clever_pred`, `trip_event_bustime`                                                             | Maps to `tripid` in real-time feeds        |
| `DAY`               | `gtfs_trip`, `gtfs_block`, `gtfs_calendar_dates`, `trip_event_bustime`, `trip_event_bustime_to_block`        | Weekday context for filtering trips/blocks |

---

### **Temporal Joins**

| Source Table         | Time Column       | Target Table                  | Matching Rule                                |
| -------------------- | ----------------- | ----------------------------- | -------------------------------------------- |
| `getvehicles`        | `timestamp`       | `trip_event_bustime`          | Join to `start_timestamp` (approx. or fuzzy) |
| `clever_pred`        | `timestamp`       | `getvehicles`                 | Match within ±2 minutes                      |
| `trip_event_bustime` | `start_timestamp` | `trip_event_bustime_to_block` | Used to group trips into blocks              |