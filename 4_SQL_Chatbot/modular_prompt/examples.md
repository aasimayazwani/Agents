# Example Applications

**Q:** What is the current location of bus 2401?  
**A:** Use `getvehicles`. Filter on vid='2401'. Return lat/lon and timestamp.

**Q:** What is the predicted SOC for bus 2402?  
**A:** Use `clever_pred`. Filter by bus_id='2402'. Use latest timestamp.

**Q:** Tell me about bus 2403’s last trip.  
**A:** Use `trip_event_bustime`. Filter on vid and max(start_timestamp). Join with gtfs_trip if needed.