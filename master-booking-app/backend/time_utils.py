"""Общие helpers для работы с интервалами времени и расписанием."""
from datetime import date, time

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
END_OF_DAY = time(23, 59, 59)


def time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def time_overlaps(start1: time, end1: time, start2: time, end2: time) -> bool:
    return start1 < end2 and start2 < end1


def interval_end(start: time, duration_minutes: int) -> time:
    total = time_to_minutes(start) + duration_minutes
    return time(total // 60, total % 60) if total < 24 * 60 else END_OF_DAY


def intervals_overlap(
    t1: time, d1: int,
    t2: time, d2: int,
) -> bool:
    return time_overlaps(t1, interval_end(t1, d1), t2, interval_end(t2, d2))


def is_schedule_date_excluded(schedule: dict | None, target_date: date) -> bool:
    """Return True for a disabled single date or a disabled inclusive range."""
    for item in (schedule or {}).get("exceptions", []):
        if isinstance(item, str):
            if item == target_date.isoformat():
                return True
            continue
        start = item.get("start") or item.get("date")
        end = item.get("end") or start
        if start and end and start <= target_date.isoformat() <= end:
            return True
    return False


def resolve_day_schedule(schedule: dict | None, target_date: date) -> dict | None:
    """Support both named weekdays and legacy schedules stored by list position."""
    days = (schedule or {}).get("days", [])
    day_index = target_date.weekday()
    day_name = DAY_NAMES[day_index]
    named = next((day for day in days if day.get("day") == day_name), None)
    if named:
        return named
    if 0 <= day_index < len(days):
        fallback = days[day_index] or {}
        if isinstance(fallback, dict):
            return {**fallback, "day": fallback.get("day") or day_name}
    return None
