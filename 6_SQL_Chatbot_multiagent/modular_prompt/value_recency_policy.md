# Value Recency Policy

- When a user refers to **"current"** values — such as current SOC, current temperature, or current miles driven — you must interpret that as the **most recent value recorded** for that variable.

- This means you should:
  - Use `ORDER BY timestamp DESC` or equivalent
  - Use `LIMIT 1` to get the latest record
  - Join on the latest available timestamp if combining multiple tables

- Examples of user terms that imply this behavior:
  - "Current SOC"
  - "Latest temperature"
  - "Most recent odometer reading"
  - "Now", "at this time", "as of today"

- Only deviate from this behavior if the user explicitly requests a specific time, date, or historical range.
