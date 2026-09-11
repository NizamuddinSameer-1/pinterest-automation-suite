import urllib.request
import re

urls = [
    "https://flow.google.com/asb/AB-nOUa7lw-uXSjI6V0li8itrjoyeOOYMwia7sxKrEkDUrKMjevj0N3WiH2Epyko2d8BFAvui_e8ayiN6tPjwmweu5BZz3U88XlOEm-ejbffvXs2vYfjBu-wWaTCalvlzRAF-0zU_4nEu6oeksEW2YiVf23RmzvhVwI7pLNeJghhYg=s512-rw",
    "https://flow.google.com/asb/AB-nOUY_lnczfwwvVkQws26H7XHR_sAEv5hemI3YDCWd3bl3uyGiBezPVk8jjW0DPyVI7jXThrPvhtQuR6QXJCav0w9hH-A1XAz03yLcBGPDVoBwT3X0Om9ZYJswR-MafPxWLl1tJI5D9e_5D2xj_3OFAexlxlxdS0u8sgfwXJo-Lw=s512-rw",
    "https://flow.google.com/asb/AB-nOUYjiCK2vavOdUOUzUk5Tl25AuEe-cIpASNY7Vs3gpyyXLIT_twizcbRbQi-KyUdDLwmODlsG8pXochAUU0a40zusbUmdEQqSGwRmdip0j0NaWTvNZ5-479glOyaLtVduvZ6_VoXsjPgaOjuTUwSFjYaoTB6OO7lT_U5m5z6mw=s512-rw",
    "https://flow.google.com/asb/AB-nOUZCPPRkK-6IcBhEZ7Ncb1dpY4P-UWSJ7CcrkxfBdDdZMh4i1s4b9etLyum6sh7b7yIymg5VXwVfoRtFfLkjWaAt81VYp9XTFpdx2uE-Lm-l5mSI-124Az9H7VNcTgNL4daiCaCyZprIcGtR6R3V7l7ftk1X65_iIOK9pavtrw=s512-rw"
]

for idx, u in enumerate(urls, 1):
    u_full = re.sub(r"=s\d+.*$", "=s0", u)
    req = urllib.request.Request(u_full, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            print(f"Var #{idx}: status {resp.status}, size {len(data)} bytes ({len(data)//1024} KB)")
    except Exception as e:
        print(f"Var #{idx} error: {e}")
