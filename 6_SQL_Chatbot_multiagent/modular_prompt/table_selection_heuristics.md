# Table Selection Guidelines

## 🎯 Primary Goal

Your primary goal is to **correctly identify and utilize the appropriate database tables** based on user queries. This requires understanding the user’s intent, mapping it to one or more tables, and gracefully handling any ambiguity or errors that arise.

---

## 📘 Guidelines for Table Selection

| Step                 | What to Do                                                                                                                                     | Example                                                                     |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **Context Analysis** | Analyze the query for intent and key nouns/verbs to decide what data domain is being requested.                                                | “Where is bus 2401 now?” → real‑time location → `getvehicles`               |
| **Table Lookup**     | Scan the schema descriptions and common‑query hints to shortlist candidate tables for the chosen domain.                                       | “end‑of‑block SOC” → shortlist `clever_pred`, `trip_event_bustime_to_block` |
| **Table Matching**   | Choose the table(s) whose key variables best align with the query. Prioritize exact matches to terms like *block*, *SOC*, *trip history*, etc. | “block information” → `gtfs_block`                                          |
| **Error Handling**   | If no clear match: (1) ask clarifying question, (2) offer best guesses.                                                                        | “Do you need real‑time or historical data?”                                 |

---

## 🛠️ Fallback Logic

* **Clarify** → *“Do you want real‑time or historical data?”*
* **Suggest** → *“Did you mean `getvehicles` for current status?”*
* **List Options** → Provide 2‑3 likely tables with one‑line summaries if still uncertain.

---

> **Remember:** When in doubt, ask the user rather than guessing. Accurate table selection is the foundation of reliable query generation.
