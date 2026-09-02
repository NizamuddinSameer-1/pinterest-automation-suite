"""
When should each pin in a batch go out?

Pinterest's own scheduler holds a pin and publishes it without this machine
being awake, so "bulk scheduling" means: work out N future times, then set each
one in Pinterest's builder. Working out the times is arithmetic with a few hard
edges, so it lives here — pure, and executed directly by the verifier:

  * Pinterest will not accept a time that has already passed, and greys out
    anything further than about 30 days ahead. Silently clamping or dropping
    such a time would publish a pin at a moment nobody asked for, so both are
    refused loudly instead.
  * A batch larger than one day's appetite has to roll onto the next day. Two
    ways to say that: "every 90 minutes, at most 15 a day", or "at 09:00, 14:00
    and 20:00 every day".
  * Times are computed and returned as aware UTC, but Pinterest's builder shows
    and accepts *local* time — so the publisher converts with `.astimezone()`
    immediately before typing. Keeping UTC here means the queue file, the API
    and the logs all speak one unambiguous timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

#: How far ahead Pinterest's scheduler accepts a pin. Its date picker greys out
#: later days, so asking for one only wastes a browser session.
HORIZON_DAYS = 30

#: Pinterest rejects a time that has effectively already arrived. The headroom
#: also covers however long the batch itself takes to type.
MIN_LEAD_MINUTES = 10

#: Pinterest caps how many pins may sit scheduled at once. The real ceiling is
#: per-account and undocumented, so this is reported as a note, never enforced.
SOFT_MAX_SCHEDULED = 100


class PlanError(ValueError):
    """The requested spacing cannot be turned into times Pinterest will accept."""


@dataclass(frozen=True)
class SchedulePlan:
    """N future times, in order, plus anything the operator should know."""

    times: tuple[datetime, ...]
    notes: tuple[str, ...] = ()

    def local_strings(self) -> tuple[str, ...]:
        """The same times as the operator will see them in Pinterest's UI."""
        return tuple(t.astimezone().strftime("%Y-%m-%d %H:%M") for t in self.times)

    def per_day(self) -> dict[str, int]:
        """How many pins land on each local calendar day, for the UI preview."""
        counted: dict[str, int] = {}
        for t in self.times:
            key = t.astimezone().strftime("%Y-%m-%d")
            counted[key] = counted.get(key, 0) + 1
        return counted


_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%H%M", "%I:%M %p", "%I:%M%p", "%I %p")


def parse_daily_slots(slots) -> tuple[time, ...]:
    """
    Turn ``["09:00", "14:00", "8:30 pm"]`` into sorted, de-duplicated times of day.

    A slot the operator cannot read back is a slot that will publish at the wrong
    hour, so an unparseable string raises instead of being skipped.
    """
    parsed: list[time] = []
    for raw in slots or ():
        if isinstance(raw, time):
            parsed.append(raw.replace(second=0, microsecond=0))
            continue
        text = str(raw).strip()
        if not text:
            continue
        for fmt in _TIME_FORMATS:
            try:
                parsed.append(datetime.strptime(text.upper(), fmt).time().replace(second=0, microsecond=0))
                break
            except ValueError:
                continue
        else:
            raise PlanError(
                f"Could not read {raw!r} as a time of day. Use 24-hour HH:MM — "
                "for example 09:00, 14:30, 20:00."
            )
    return tuple(sorted(set(parsed)))


def _by_interval(
    count: int,
    start: datetime,
    interval_minutes: int,
    per_day_cap: int | None,
) -> list[datetime]:
    """
    Mode 1 — start time, then one pin every `interval_minutes`.

    With a per-day cap, each new day restarts at the *same local time of day* as
    the batch start, which is what "15 a day, 90 minutes apart" means to a human.
    Without a cap the run simply continues across midnight.

    The cap therefore counts pins per *run day* — a run that begins at 18:30 and
    spaces pins 90 minutes apart will spill its last few past midnight, so
    `SchedulePlan.per_day()` (which counts calendar days) can show fewer than the
    cap on the first day. Pinterest does not care; the operator might, which is
    why the preview shows the real dates rather than the requested cap.
    """
    step = timedelta(minutes=interval_minutes)
    local_start = start.astimezone()
    out: list[datetime] = []
    day = 0
    while len(out) < count:
        day_base = local_start + timedelta(days=day)
        room = per_day_cap if per_day_cap else (count - len(out))
        for i in range(room):
            if len(out) >= count:
                break
            out.append((day_base + step * i).astimezone(timezone.utc))
        day += 1
    return out


def _by_slots(
    count: int,
    start: datetime,
    slots: tuple[time, ...],
    per_day_cap: int | None,
    earliest: datetime,
) -> tuple[list[datetime], int]:
    """
    Mode 2 — the same fixed times of day, filled day after day.

    Slots that have already gone by on the first day are skipped (not moved), and
    the count of skipped slots comes back so the caller can say so out loud.
    """
    per_day = min(per_day_cap, len(slots)) if per_day_cap else len(slots)
    floor = max(earliest, start)
    out: list[datetime] = []
    skipped = 0
    day = 0
    while len(out) < count and day <= HORIZON_DAYS + 1:
        calendar_day = (start.astimezone() + timedelta(days=day)).date()
        used = 0
        for slot in slots:
            if used >= per_day or len(out) >= count:
                break
            candidate = datetime.combine(calendar_day, slot).astimezone(timezone.utc)
            if candidate < floor:
                skipped += 1
                continue
            out.append(candidate)
            used += 1
        day += 1
    return out, skipped


def plan_publish_times(
    count: int,
    start: datetime,
    *,
    interval_minutes: int | None = None,
    daily_slots=None,
    per_day_cap: int | None = None,
    horizon_days: int = HORIZON_DAYS,
    now: datetime | None = None,
) -> SchedulePlan:
    """
    Work out when each of `count` pins should publish.

    Give *either* `interval_minutes` (mode 1) *or* `daily_slots` (mode 2).
    `per_day_cap` limits how many pins land on one local day in either mode.
    `start` must be timezone-aware — parse operator input with
    `pinterest_service.parse_scheduled_time` first, which treats a bare
    "2026-09-01 09:00" as local time.

    Raises `PlanError` rather than returning a shorter plan: a batch that quietly
    schedules 12 of 20 pins is worse than one that says which 8 did not fit.
    """
    if count <= 0:
        raise PlanError("Nothing to schedule — select at least one pin.")
    if start.tzinfo is None:
        raise PlanError(
            "The start time carries no timezone. Pinterest's builder speaks local "
            "time, so parse it with parse_scheduled_time() before planning."
        )
    if per_day_cap is not None and per_day_cap <= 0:
        raise PlanError("A per-day cap of zero or less would schedule nothing.")

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = start.astimezone(timezone.utc)
    earliest = now + timedelta(minutes=MIN_LEAD_MINUTES)
    slots = parse_daily_slots(daily_slots)
    notes: list[str] = []

    if slots:
        if interval_minutes:
            notes.append(
                f"Both fixed daily slots and a {interval_minutes}-minute interval were "
                "given; the slots are used, because an interval cannot also honour "
                "fixed times of day."
            )
        times, skipped = _by_slots(count, start, slots, per_day_cap, earliest)
        if skipped:
            notes.append(
                f"{skipped} slot(s) on the first day had already passed, so the batch "
                "starts at the next free slot."
            )
    else:
        if not interval_minutes or interval_minutes <= 0:
            raise PlanError(
                "No spacing given. Either set an interval in minutes (e.g. every 90 "
                "minutes) or list daily slots (e.g. 09:00, 14:00, 20:00)."
            )
        if start < earliest:
            raise PlanError(
                f"The start time {start.astimezone():%Y-%m-%d %H:%M} is in the past or "
                f"less than {MIN_LEAD_MINUTES} minutes away. Pinterest refuses a time "
                "it considers already arrived — pick a later start."
            )
        times = _by_interval(count, start, interval_minutes, per_day_cap)

    if len(times) != count:
        raise PlanError(
            f"Could only place {len(times)} of {count} pins inside "
            f"{horizon_days} days with this spacing. Add more daily slots, raise the "
            "per-day cap, or schedule the rest in a later batch."
        )

    horizon = now + timedelta(days=horizon_days)
    beyond = [t for t in times if t > horizon]
    if beyond:
        fits = count - len(beyond)
        raise PlanError(
            f"{len(beyond)} of {count} pins would land after "
            f"{horizon.astimezone():%Y-%m-%d %H:%M}, and Pinterest's date picker greys "
            f"out anything more than ~{horizon_days} days ahead. Only {fits} fit — "
            "shorten the interval, raise the per-day cap, or send a smaller batch."
        )

    stale = [t for t in times if t < earliest]
    if stale:
        raise PlanError(
            f"{len(stale)} planned time(s) are in the past or under "
            f"{MIN_LEAD_MINUTES} minutes away; Pinterest would reject them."
        )

    if count > SOFT_MAX_SCHEDULED:
        notes.append(
            f"{count} pins in one batch — Pinterest limits how many may sit scheduled "
            f"at once (around {SOFT_MAX_SCHEDULED}). If it starts refusing, send the "
            "rest after some have published."
        )

    busiest = max(SchedulePlan(tuple(times)).per_day().values())
    if busiest > 25:
        notes.append(
            f"{busiest} pins on one day is heavy for a single account and risks being "
            "treated as spam. 10–25 a day is the usual safe ceiling."
        )

    return SchedulePlan(tuple(times), tuple(notes))
