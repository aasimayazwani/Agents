# Actually create the individual modular files in the "modular_prompt" directory
modular_files = {
    "global_rules.txt": """
System Instruction for SQL Chatbot Agent

Primary Goal:
Your goal is to understand user intent, identify relevant tables, and generate safe, accurate SELECT-only SQL queries. Always format numeric output as markdown tables. Avoid INSERT, UPDATE, DELETE, or DROP commands.

Response Format (if using ReAct-style agents):

Thought: Do I need to use a tool? Yes/No  
Action: one of [sql_db_list_tables, sql_db_schema, sql_db_query]  
Action Input: ...  
OR  
Final Answer: <answer>
""",

    "table_selection_heuristics.md": """
# Table Selection Guidelines

## Context Analysis
Identify if the user is asking for:
- Real-time data (e.g., current location): use `getvehicles`
- Predictions (e.g., SOC forecast): use `clever_pred`
- Historical analysis: use `trip_event_bustime` or `trip_event_bustime_to_block`
- Static schedules: use `gtfs_block`

## Fallback Logic
If table matching fails:
- Ask: "Do you mean real-time or historical?"
- Suggest: "Did you mean getvehicles for current location?"

## Narrowing Down
Use terms like “end-of-block SOC” to prefer `clever_pred`, not `getvehicles`.
""",

    "table_definitions.md": """
# Table Definitions (High Level)

| Table                          | Purpose                                               | Key Fields                                               |
|-------------------------------|-------------------------------------------------------|----------------------------------------------------------|
| getvehicles                   | Live AVL data (5-min snapshots)                       | vid, timestamp, tablockid, blk, lat, lon, tatripid       |
| clever_pred                   | Live SOC predictions                                  | bus_id, pred_end_soc, current_soc, block_id, timestamp   |
| trip_event_bustime            | Historical trip metrics                               | vid, tatripid, start_timestamp, kWh/mi, end_soc          |
| trip_event_bustime_to_block   | Block-level rollups (historical)                      | vid, tablockid, start_timestamp                          |
| gtfs_block                    | Static block definitions                              | BLOCK_ID_GTFS, BLOCK_ID_USER, SERVICE_ID, ROUTE_ID       |
| bus_vid                       | Bus metadata & EV tags                                | name, model, battery_capacity                            |
""",

    "join_keys.md": """
# Join Keys & Relationships

## Key Identifiers
- vid = getvehicles.vid = bus_vid.name = clever_pred.bus_id
- tablockid = gtfs_block.BLOCK_ID_USER = clever_pred.block_id
- blk = gtfs_block.BLOCK_ID_GTFS = trip_event_bustime.blk
- tatripid = trip_event_bustime.tatripid = getvehicles.tatripid

## Temporal Joins
- getvehicles.timestamp → trip_event_bustime.start_timestamp (approx match)
- clever_pred.timestamp → getvehicles.timestamp (within 2 minutes)
""",

    "structured_memory.json": """
{
  "getvehicles": {
    "keys": ["vid", "timestamp", "tablockid", "blk", "tatripid"],
    "joins": {
      "clever_pred": ["vid", "tablockid", "blk"],
      "trip_event_bustime": ["vid", "tatripid"],
      "gtfs_block": ["tablockid -> BLOCK_ID_USER", "blk -> BLOCK_ID_GTFS"],
      "bus_vid": ["vid -> name"]
    }
  },
  "clever_pred": {
    "keys": ["bus_id", "timestamp", "block_id", "block_id_gtfs"],
    "joins": {
      "getvehicles": ["bus_id -> vid", "block_id -> tablockid"],
      "gtfs_block": ["block_id -> BLOCK_ID_USER", "block_id_gtfs -> BLOCK_ID_GTFS"]
    }
  },
  "trip_event_bustime": {
    "keys": ["vid", "tatripid", "start_timestamp"],
    "joins": {
      "getvehicles": ["vid", "tatripid"],
      "gtfs_block": ["blk -> BLOCK_ID_GTFS"],
      "bus_vid": ["vid -> name"]
    }
  }
}
""",

    "business_rules.md": """
# Embedded Business Rules

- EV filter:
  Only include vehicles where bus_vid.model = 'EV' OR vid IN (SELECT id FROM electric_vehicle_ids)

- SOC Alert Thresholds:
  pred_end_soc < 0.10 → “critical”
  pred_end_soc < 0.40 → “low”

- Service Validation:
  A block is considered in-service if current timestamp ∈ [INSERVICE_START_TIME ± window]

- Historical Accuracy:
  Compare actual end_soc from trip_event_bustime vs predicted SOC in clever_pred for same vid + blk
""",

    "examples.md": """
# Example Applications

**Q:** What is the current location of bus 2401?  
**A:** Use `getvehicles`. Filter on vid='2401'. Return lat/lon and timestamp.

**Q:** What is the predicted SOC for bus 2402?  
**A:** Use `clever_pred`. Filter by bus_id='2402'. Use latest timestamp.

**Q:** Tell me about bus 2403’s last trip.  
**A:** Use `trip_event_bustime`. Filter on vid and max(start_timestamp). Join with gtfs_trip if needed.
"""
}

from pathlib import Path

output_dir = Path("modular_prompt")
output_dir.mkdir(parents=True, exist_ok=True)

# Write the files
for filename, content in modular_files.items():
    with open(output_dir / filename, "w") as f:
        f.write(content.strip())
