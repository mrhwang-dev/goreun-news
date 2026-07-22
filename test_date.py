import sys
from pathlib import Path
sys.path.append(".")
from build_site import _date_strip
dates = [("2026-07-23", "2026-07-23-02"), ("2026-07-22", "2026-07-22-23")]
today = "2026-07-23"
print("NEWS:", _date_strip(dates, today, "archive"))
print("BLINDSPOT:", _date_strip(dates, "", "anchor"))
