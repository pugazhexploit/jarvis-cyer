"""
World & India Time Module for JARVIS.
Provides real-time India Standard Time (IST), System Time, and World Time for major global cities.
"""
from datetime import datetime, timezone, timedelta
import re

# IST is always UTC+05:30
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET, name="IST")

# Major world cities and standard UTC offsets (hours, minutes)
WORLD_ZONES = {
    "india":        {"offset": (5, 30),  "label": "India (IST)",       "abbr": "IST"},
    "ist":          {"offset": (5, 30),  "label": "India Standard Time", "abbr": "IST"},
    "kolkata":      {"offset": (5, 30),  "label": "Kolkata (IST)",     "abbr": "IST"},
    "delhi":        {"offset": (5, 30),  "label": "New Delhi (IST)",   "abbr": "IST"},
    "mumbai":       {"offset": (5, 30),  "label": "Mumbai (IST)",      "abbr": "IST"},
    "chennai":      {"offset": (5, 30),  "label": "Chennai (IST)",     "abbr": "IST"},
    "bengaluru":    {"offset": (5, 30),  "label": "Bengaluru (IST)",   "abbr": "IST"},
    
    "utc":          {"offset": (0, 0),   "label": "UTC / GMT",         "abbr": "UTC"},
    "gmt":          {"offset": (0, 0),   "label": "Greenwich Mean Time", "abbr": "GMT"},
    "london":       {"offset": (1, 0),   "label": "London (BST)",      "abbr": "BST"},
    "uk":           {"offset": (1, 0),   "label": "United Kingdom",    "abbr": "BST"},
    
    "new york":     {"offset": (-4, 0),  "label": "New York (EDT)",    "abbr": "EDT"},
    "nyc":          {"offset": (-4, 0),  "label": "New York City",     "abbr": "EDT"},
    "est":          {"offset": (-5, 0),  "label": "Eastern Standard",  "abbr": "EST"},
    "edt":          {"offset": (-4, 0),  "label": "Eastern Daylight",  "abbr": "EDT"},
    
    "los angeles":  {"offset": (-7, 0),  "label": "Los Angeles (PDT)", "abbr": "PDT"},
    "california":   {"offset": (-7, 0),  "label": "California (PDT)",  "abbr": "PDT"},
    "pst":          {"offset": (-8, 0),  "label": "Pacific Standard",  "abbr": "PST"},
    "pdt":          {"offset": (-7, 0),  "label": "Pacific Daylight",  "abbr": "PDT"},
    
    "chicago":      {"offset": (-5, 0),  "label": "Chicago (CDT)",     "abbr": "CDT"},
    "cst":          {"offset": (-6, 0),  "label": "Central Standard",  "abbr": "CST"},
    "cdt":          {"offset": (-5, 0),  "label": "Central Daylight",  "abbr": "CDT"},
    
    "tokyo":        {"offset": (9, 0),   "label": "Tokyo (JST)",       "abbr": "JST"},
    "japan":        {"offset": (9, 0),   "label": "Japan (JST)",       "abbr": "JST"},
    "jst":          {"offset": (9, 0),   "label": "Japan Standard",    "abbr": "JST"},
    
    "dubai":        {"offset": (4, 0),   "label": "Dubai (GST)",       "abbr": "GST"},
    "uae":          {"offset": (4, 0),   "label": "UAE (GST)",         "abbr": "GST"},
    
    "singapore":    {"offset": (8, 0),   "label": "Singapore (SGT)",   "abbr": "SGT"},
    "hong kong":    {"offset": (8, 0),   "label": "Hong Kong (HKT)",   "abbr": "HKT"},
    
    "sydney":       {"offset": (10, 0),  "label": "Sydney (AEST)",     "abbr": "AEST"},
    "australia":    {"offset": (10, 0),  "label": "Australia (AEST)",  "abbr": "AEST"},
    
    "paris":        {"offset": (2, 0),   "label": "Paris (CEST)",      "abbr": "CEST"},
    "berlin":       {"offset": (2, 0),   "label": "Berlin (CEST)",     "abbr": "CEST"},
    "germany":      {"offset": (2, 0),   "label": "Germany (CEST)",    "abbr": "CEST"},
    "france":       {"offset": (2, 0),   "label": "France (CEST)",     "abbr": "CEST"},
    
    "moscow":       {"offset": (3, 0),   "label": "Moscow (MSK)",      "abbr": "MSK"},
    "russia":       {"offset": (3, 0),   "label": "Moscow (MSK)",      "abbr": "MSK"},
}


def get_ist_time() -> datetime:
    """Returns the current datetime in India Standard Time (IST, UTC+05:30)."""
    return datetime.now(timezone.utc).astimezone(IST_TZ)


def get_current_time(location: str = "india") -> str:
    """
    Returns the current time formatted for JARVIS.
    Defaults to India Standard Time (IST) along with major world times.
    If a specific city/country is queried, returns that location's exact time and offset from IST.
    """
    loc_clean = (location or "india").strip().lower()
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST_TZ)
    now_sys = datetime.now()

    # If the user asked specifically about system/local time
    if loc_clean in ("system", "local", "pc", "computer"):
        sys_tz_name = datetime.now().astimezone().tzname() or "Local"
        return (
            f"Current System Time: {now_sys.strftime('%A, %B %d, %Y - %I:%M:%S %p')} ({sys_tz_name})\n"
            f"India Time (IST): {now_ist.strftime('%I:%M:%S %p IST')}"
        )

    # Check if a specific world zone was requested
    matched_zone = None
    for k, v in WORLD_ZONES.items():
        if k in loc_clean or loc_clean in k:
            matched_zone = v
            break

    if matched_zone and loc_clean not in ("all", "world", "india", "ist", "kolkata", "delhi", "mumbai", "chennai", "bengaluru"):
        h, m = matched_zone["offset"]
        tz = timezone(timedelta(hours=h, minutes=m), name=matched_zone["abbr"])
        loc_dt = now_utc.astimezone(tz)
        
        # Calculate difference compared to India Time (IST)
        diff_hours = (h + m / 60.0) - 5.5
        if diff_hours == 0:
            diff_str = "same time as India (IST)"
        elif diff_hours > 0:
            diff_str = f"{abs(diff_hours):.1f} hours ahead of India (IST)"
        else:
            diff_str = f"{abs(diff_hours):.1f} hours behind India (IST)"

        return (
            f"{matched_zone['label']}: {loc_dt.strftime('%A, %B %d, %Y - %I:%M:%S %p')} ({matched_zone['abbr']})\n"
            f"Comparison: {diff_str}\n"
            f"India Time (IST): {now_ist.strftime('%I:%M:%S %p')}"
        )

    # Default / General World Time overview with India Time prominently featured
    lines = [
        f"India Time (IST): {now_ist.strftime('%A, %B %d, %Y - %I:%M:%S %p')}",
        f"System Time:     {now_sys.strftime('%I:%M:%S %p')}",
        f"World Time (UTC): {now_utc.strftime('%I:%M:%S %p UTC')}",
        "",
        "Major World Clocks:",
    ]
    
    cities = [
        ("New York (EDT)", timedelta(hours=-4)),
        ("London (BST)",   timedelta(hours=1)),
        ("Dubai (GST)",    timedelta(hours=4)),
        ("Tokyo (JST)",    timedelta(hours=9)),
        ("Singapore (SGT)", timedelta(hours=8)),
    ]
    for name, offset in cities:
        dt = now_utc.astimezone(timezone(offset))
        lines.append(f"  * {name:16}: {dt.strftime('%I:%M %p (%a)')}")

    return "\n".join(lines)
