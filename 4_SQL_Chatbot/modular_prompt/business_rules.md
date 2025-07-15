# EMBEDDED BUSINESS RULES – vehicles.db

## 🔋 Electric Vehicle Filtering

- A vehicle is considered an EV if:
  - `bus_vid.model = 'EV'`
  - OR `vid` is found in the `electric_vehicle_ids` table:
    ```sql
    vid IN (SELECT id FROM electric_vehicle_ids)
    ```

- Only include these EVs when the user asks about:
  - SOC (State of Charge)
  - Battery performance
  - Charging behavior
  - Electric range or energy efficiency

---

## 🚨 SOC Alert Thresholds

Define SOC (State of Charge) alert levels based on `pred_end_soc` from `clever_pred`:

| Threshold            | Alert Level |
|----------------------|-------------|
| `pred_end_soc < 0.10` | Critical    |
| `pred_end_soc < 0.40` | Low         |
| `≥ 0.40`              | Normal      |

You must:
- Report the correct alert category.
- Optionally highlight SOC status when displaying predicted results.

---

## 🚌 Service Validation Rule

A vehicle block is considered **in service** if the current time falls within a defined operating window.

- A block is in service if:
  ```sql
  CURRENT_TIMESTAMP BETWEEN INSERVICE_START_TIME - buffer AND INSERVICE_START_TIME + buffer
````

* Replace `buffer` with an acceptable window (e.g., ±15 minutes) if not specified by the user.
* Use this logic to include or exclude records from real-time queries.

---

## 📉 Historical vs. Predicted SOC Accuracy

When comparing **prediction accuracy**:

* Join `trip_event_bustime` and `clever_pred` on:

  * `vid`
  * `blk` or `tablockid`
  * `day` or a closely matching `timestamp`

* Then compare:

  ```sql
  trip_event_bustime.end_soc - clever_pred.pred_end_soc
  ```

* You may calculate error metrics like:

  * Absolute error: `ABS(actual - predicted)`
  * Percent error: `(actual - predicted) / predicted`

Use this when asked to validate or audit model predictions.

```