# Query Generation Guidelines

## Result Scope Defaults
- Unless the user asks for only one row, **do not use `LIMIT 1`** in your queries.
- If in doubt, **fetch all matching rows** and let the user filter or summarize later.
- When ordering is required (e.g., by timestamp), include `ORDER BY` only if the user asks for "latest", "oldest", or specific sorting.
- Use `GROUP BY`, `COUNT`, or `DISTINCT` where appropriate — but never assume aggregation unless explicitly requested.

## Query Accuracy

- Always align selected columns with the user's intent.
- When querying a block-level table (like `trip_event_bustime_to_block`), include columns such as `vid`, `tablockid`, `start_timestamp`, and `energy_used`.
- Prefer named columns over `SELECT *` unless the user wants the full table.

## Temporal Filters

- If the user mentions time frames (e.g., “last week”, “yesterday”), convert that into a proper `WHERE` clause using `stsd` or `timestamp` depending on the table.
- For real-time tables like `getvehicles`, use `timestamp`.
- For historical tables like `trip_event_bustime`, use `stsd` or `start_timestamp`.

## Examples

**Bad SQL** (Too narrow):

```sql
SELECT * FROM trip_event_bustime_to_block ORDER BY start_timestamp DESC LIMIT 1;

Good SQL (Wide scope):
SELECT * FROM trip_event_bustime_to_block WHERE stsd BETWEEN '2025-06-01' AND '2025-06-08';

