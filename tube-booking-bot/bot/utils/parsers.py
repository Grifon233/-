import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import pytz

from bot.config import ATHLETES
from bot.config import WEEKDAYS

BUSINESS_TIMEZONE = pytz.timezone("Asia/Yekaterinburg")


def normalize_text(text: str) -> str:
    """Normalizes text: lowercase, removes extra spaces."""
    return re.sub(r'\s+', ' ', text.lower().strip())

def _normalize_input(text: str) -> str:
    """Normalize input for parser while preserving Cyrillic text."""
    text = text.replace('\u00a0', ' ')
    text = re.sub(r'(?<=[а-яё])(?=\d)', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<=\d)(?=[а-яё])', ' ', text, flags=re.IGNORECASE)
    return normalize_text(text)

def _get_today_date() -> str:
    """Get today's date in DD.MM format."""
    return datetime.now(BUSINESS_TIMEZONE).strftime("%d.%m")


def resolve_training_datetime(date_str: str, time_str: Optional[str] = None) -> Optional[datetime]:
    """Resolve DD.MM and optional HH:MM to the next matching Yekaterinburg datetime."""
    tz = BUSINESS_TIMEZONE
    now = datetime.now(tz)
    try:
        day, month = map(int, date_str.split("."))
        candidate = tz.localize(datetime(now.year, month, day))
    except (TypeError, ValueError):
        return None

    if candidate.date() < now.date():
        try:
            candidate = candidate.replace(year=candidate.year + 1)
        except ValueError:
            return None

    if time_str:
        parsed_time = _parse_time_string(time_str)
        if not parsed_time:
            return None
        hour, minute = map(int, parsed_time.split(":"))
        candidate = candidate.replace(hour=hour, minute=minute)

    return candidate


def _parse_time_string(time_str: str) -> Optional[str]:
    """Convert various time formats to HH:MM. Returns None if invalid."""
    time_str = time_str.strip().lower()

    patterns = [
        r'^(\d{1,2})[:.\-](\d{2})$',
        r'^(\d{1,2})([\.\-])(\d{2})$',
    ]

    for pattern in patterns:
        match = re.match(pattern, time_str)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour < 24 and 0 <= minute < 60:
                return f"{hour:02d}:{minute:02d}"

    match = re.match(r'^(\d{1,2})$', time_str)
    if match:
        hour = int(match.group(1))
        if 0 <= hour < 24:
            return f"{hour:02d}:00"

    match = re.match(r'^(\d{1,2})\s*(утра|дня|вечера|ночи)$', time_str)
    if match:
        hour = int(match.group(1))
        period = match.group(2)
        if period == "вечера" and hour < 12:
            hour += 12
        elif period == "утра" and hour == 12:
            hour = 0
        elif period == "ночи" and hour < 6:
            hour += 12
        if 0 <= hour < 24:
            return f"{hour:02d}:00"

    return None

def _extract_times_from_text(text: str) -> List[Tuple[str, Tuple[int, int]]]:
    """
    Extract all time mentions from text with their positions.
    Returns list of (time_value, (start_pos, end_pos)).
    Handles all trainer time formats.

    Key distinction from dates:
    - TIME HH:MM/HH.MM/HH-MM where MM is valid minute (00-59)
    - DATE DD.MM where DD is day (01-31) and MM is month (01-12)
    - When format is ambiguous, context determines interpretation
    """
    times = []
    consumed_spans = []

    def overlaps(span: Tuple[int, int]) -> bool:
        return any(span[0] < used[1] and used[0] < span[1] for used in consumed_spans)

    # Pattern 0: Time with period must be extracted before bare hours.
    period_pattern = r'\b(\d{1,2})\s*(утра|дня|вечера|ночи)\b'
    for match in re.finditer(period_pattern, text):
        hour = int(match.group(1))
        period = match.group(2)
        span = match.span()

        adjusted_hour = hour
        if period == "вечера" and 1 <= hour < 12:
            adjusted_hour = hour + 12
        elif period == "дня" and 1 <= hour < 12:
            adjusted_hour = hour + 12
        elif period == "утра" and hour == 12:
            adjusted_hour = 0
        elif period == "ночи" and hour == 12:
            adjusted_hour = 0
        elif period == "ночи" and 1 <= hour < 6:
            adjusted_hour = hour

        if 0 <= adjusted_hour < 24:
            times.append((f"{adjusted_hour:02d}:00", span))
            consumed_spans.append(span)

    # Pattern 1: HH:MM, HH.MM, HH-MM with valid minutes (00-59)
    for match in re.finditer(r'\b(\d{1,2})[:.\-](\d{2})\b', text):
        span = match.span()
        if overlaps(span):
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            times.append((f"{hour:02d}:{minute:02d}", span))
            consumed_spans.append(span)

    # Pattern 2: Single hour "в 16" or "16"
    for match in re.finditer(r'\b(?:в\s*)?(\d{1,2})\b', text):
        hour = int(match.group(1))
        span = match.span()
        after = text[span[1]:span[1] + 8]
        if overlaps(span) or re.match(r'\s*(утра|дня|вечера|ночи)\b', after):
            continue
        if 0 <= hour < 24:
            is_duplicate = any(
                span[0] >= t[1][0] and span[1] <= t[1][1]
                for t in times
            )
            if not is_duplicate:
                times.append((f"{hour:02d}:00", span))

    return times


def _adjust_hour_by_period(hour: int, period: str) -> Optional[int]:
    if period == "вечера":
        if hour == 12:
            return 12
        if 1 <= hour < 12:
            return hour + 12
    elif period == "дня":
        if hour == 12:
            return 12
        if 1 <= hour < 12:
            return hour + 12
    elif period == "утра":
        if hour == 12:
            return 0
    elif period == "ночи":
        if hour == 12:
            return 0
    if 0 <= hour < 24:
        return hour
    return None

# ============================================================
# ATHLETE SCHEDULE PARSING (Sunday Poll)
# ============================================================

def parse_athlete_schedule(text: str) -> Optional[List[Dict[str, str]]]:
    """
    Parse athlete's schedule input with maximum flexibility.
    Handles:
    - пн 14-22 (dash)
    - пн с 14:00 до 22:00 (full)
    - пн 14.00-22.00 (dots)
    - пн с 2 до 10 вечера (PM-style)
    - пн 14 (single time = start)
    - пн14-22 (no spaces)
    - пн с14 до22 (no spaces around numbers)
    - Multiple days in one line separated by comma/semicolon
    """
    day_pattern = r'\b(пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\b'

    schedule = []
    # Split by newlines BEFORE normalizing (since normalize_text collapses newlines)
    lines = text.split('\n')
    # If only one line with multiple days (separated by ; or ,), split those too
    if len(lines) == 1:
        lines = text.replace(';', '\n').replace(',', '\n').split('\n')

    for line in lines:
        line = _normalize_input(line)
        if not line:
            continue

        day_match = re.search(day_pattern, line, re.IGNORECASE)
        if not day_match:
            continue

        day_str = day_match.group(1).lower()
        day_num = WEEKDAYS.get(day_str)
        if day_num is None:
            continue

        full_day_name = next(k for k, v in WEEKDAYS.items() if v == day_num and len(k) > 2)

        range_match = re.search(
            r'(\d{1,2})[:.\-]?(\d{0,2})\s*(?:до|-|–|\.\.\.?)\s*(\d{1,2})[:.\-]?(\d{0,2})?\s*(утра|дня|вечера|ночи)?',
            line
        )

        start_time = None
        end_time = None

        if range_match:
            start_str = range_match.group(1)
            start_min = range_match.group(2) or "00"
            end_str = range_match.group(3)
            end_min = range_match.group(4) or "00"

            start_hour, start_minute = int(start_str), int(start_min)
            end_hour, end_minute = int(end_str), int(end_min)
            period = range_match.group(5)
            if period:
                adjusted_start_hour = _adjust_hour_by_period(start_hour, period)
                adjusted_end_hour = _adjust_hour_by_period(end_hour, period)
                if adjusted_start_hour is None or adjusted_end_hour is None:
                    continue
                start_hour = adjusted_start_hour
                end_hour = adjusted_end_hour
            if not (0 <= start_hour < 24 and 0 <= end_hour < 24 and 0 <= start_minute < 60 and 0 <= end_minute < 60):
                continue
            start_time = f"{start_hour:02d}:{start_minute:02d}"
            end_time = f"{end_hour:02d}:{end_minute:02d}"

        if not start_time:
            single_match = re.search(r'\b(\d{1,2})\b', line)
            if single_match:
                hour = int(single_match.group(1))
                if 0 <= hour < 24:
                    start_time = f"{hour:02d}:00"

        if start_time:
            result = {
                "day": full_day_name,
                "start": start_time,
            }
            if end_time:
                result["end"] = end_time
            schedule.append(result)

    return schedule if schedule else None

def validate_schedule_format(text: str) -> bool:
    """Validates the schedule format by attempting to parse."""
    return parse_athlete_schedule(text) is not None

def format_schedule(schedule: List[Dict[str, str]]) -> str:
    """Formats a schedule for display."""
    lines = []
    for item in schedule:
        day = item["day"].capitalize()
        if "end" in item:
            lines.append(f"{day} с {item['start']} до {item['end']}")
        else:
            lines.append(f"{day} в {item['start']}")
    return "\n".join(lines)

def parse_schedule_display(schedule: List[Dict[str, str]]) -> str:
    """Formats a schedule for display - used in confirmation messages."""
    return format_schedule(schedule)

# ============================================================
# TRAINER MESSAGE PARSING (Scheduling)
# ============================================================

def _get_athlete_aliases() -> Dict[str, Dict]:
    """Build a flat mapping of all aliases to athlete info."""
    aliases = {}
    for telegram_id, athlete_data in ATHLETES.items():
        for alias in athlete_data.get("aliases", []):
            alias_lower = alias.lower()
            if alias_lower not in aliases:
                aliases[alias_lower] = {
                    "id": telegram_id,
                    "name": athlete_data["name"],
                    "full_name": athlete_data.get("full_name", athlete_data["name"])
                }
    return aliases


def _get_kirill_ids() -> set:
    """Get all telegram IDs for athletes named Кирилл."""
    kirill_ids = set()
    for telegram_id, athlete_data in ATHLETES.items():
        if "кирилл" in athlete_data.get("full_name", "").lower():
            kirill_ids.add(telegram_id)
    return kirill_ids

def _is_likely_date(digits: str, context_text: str, position: int) -> bool:
    """
    Determine if XX.XX pattern is likely a DATE (DD.MM) or TIME (HH.MM).
    Context: if followed by another time or end of relevant context = date
             if followed by athlete name = could be either, use heuristics
    """
    parts = digits.split('.')
    if len(parts) != 2:
        return False

    first, second = int(parts[0]), int(parts[1])

    # Valid date: DD.MM where DD is 01-31 and MM is 01-12
    if 1 <= first <= 31 and 1 <= second <= 12:
        # Check what comes after - if next to a name with no time after, probably date
        return True

    return False

def _extract_date_from_text(text: str, names: List[Dict]) -> Optional[Tuple[str, Tuple[int, int]]]:
    """
    Extract date in DD.MM format from text.
    Key insight: trainer writes "day in day" - today is default.
    So DD.MM is only recognized when it looks like a date AND is followed by athlete name.

    Examples:
    - "11.05 Маккинли 14:00" → 11.05 is date, 14:00 is time
    - "18.00 фролова" → 18.00 is TIME (not date) because MM >= 13 makes no sense as month
    - "14.15 зельдин" → 14.15 is TIME (14:15) because MM >= 13 makes no sense as month
    """
    # Find DD.MM patterns where DD is valid day and MM is valid month
    # Then check if it's followed by a name (not time)

    for match in re.finditer(r'\b(\d{1,2})\.(\d{1,2})\b', text):
        day, month = int(match.group(1)), int(match.group(2))
        span = match.span()
        match_text = match.group(0)

        # Valid date check: day 01-31, month 01-12
        if not (1 <= day <= 31 and 1 <= month <= 12):
            continue

        # Get text after this match
        after_text = text[span[1]:span[1]+50].strip()

        # Check if after the date there's a name or another identifier
        # If after date comes a time pattern (HH:MM), then this might be time not date
        # But if there's a name after, it's likely a date

        # Simple heuristic: look for athlete name after
        aliases = _get_athlete_aliases()
        found_name_after = False

        for alias in aliases:
            if after_text.startswith(alias.lower()):
                found_name_after = True
                break

        if found_name_after:
            trailing_times = _extract_times_from_text(after_text)
            if not trailing_times:
                continue
            try:
                date_obj = datetime(datetime.now(BUSINESS_TIMEZONE).year, month, day)
                return (date_obj.strftime("%d.%m"), span)
            except ValueError:
                return ("INVALID_DATE", span)

    return None

def _get_weekday_date(day_str: str, allow_same_day: bool = False) -> str:
    """Convert weekday reference to actual date."""
    day_str = day_str.lower()
    if day_str in WEEKDAYS:
        day_num = WEEKDAYS[day_str]
        today = datetime.now(BUSINESS_TIMEZONE)
        days_ahead = day_num - today.weekday()
        if days_ahead < 0 or (days_ahead == 0 and not allow_same_day):
            days_ahead += 7
        target_date = today + timedelta(days=days_ahead)
        return target_date.strftime("%d.%m")
    return None

def _extract_weekday(text: str, allow_same_day: bool = False) -> Optional[Tuple[str, Tuple[int, int]]]:
    """Extract weekday from text and convert to date."""
    pattern = r'\b(пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\b'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        day_str = match.group(1).lower()
        date_str = _get_weekday_date(day_str, allow_same_day=allow_same_day)
        if date_str:
            return (date_str, match.span())
    return None

def _remove_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for idx in range(start, end):
            chars[idx] = " "
    return "".join(chars)

def _extract_dates(
    text: str,
    names: List[Dict],
    allow_same_day_weekday: bool = False
) -> Tuple[List[Tuple[str, Tuple[int, int]]], bool]:
    dates = []
    invalid = False
    date_match = _extract_date_from_text(text, names)
    if date_match:
        if date_match[0] == "INVALID_DATE":
            invalid = True
        else:
            dates.append(date_match)
    weekday_match = _extract_weekday(text, allow_same_day=allow_same_day_weekday)
    if weekday_match:
        dates.append(weekday_match)
    tomorrow_match = re.search(r'\bзавтра\b', text, re.IGNORECASE)
    if tomorrow_match:
        target = datetime.now(BUSINESS_TIMEZONE) + timedelta(days=1)
        dates.append((target.strftime("%d.%m"), tomorrow_match.span()))
    return dates, invalid

def _extract_names(text: str, disambiguation_map: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Extract all athlete names from text."""
    names = []
    aliases = _get_athlete_aliases()
    kirill_ids = _get_kirill_ids()  # Получаем IDs всех Кириллов

    sorted_aliases = sorted(aliases.keys(), key=len, reverse=True)
    pattern = r'\b(' + '|'.join(re.escape(a) for a in sorted_aliases) + r')\b'

    ambiguous_kirill_aliases = {"кирилл", "кирил", "кир", "кирюша"}

    for match in re.finditer(pattern, text, re.IGNORECASE):
        alias_matched = match.group(1).lower()
        if alias_matched in aliases:
            info = aliases[alias_matched].copy()
            if alias_matched in ambiguous_kirill_aliases and len(kirill_ids) > 1:
                if disambiguation_map and "кирилл" in disambiguation_map:
                    chosen_id = disambiguation_map["кирилл"]
                    chosen = ATHLETES.get(chosen_id)
                    if not chosen:
                        continue
                    info = {
                        "id": chosen_id,
                        "name": chosen["name"],
                        "full_name": chosen.get("full_name", chosen["name"]),
                    }
                else:
                    for kirill_id in kirill_ids:
                        kirill_data = ATHLETES[kirill_id]
                        names.append({
                            "value": {
                                "id": kirill_id,
                                "name": kirill_data["name"],
                                "full_name": kirill_data.get("full_name", kirill_data["name"]),
                            },
                            "span": match.span(),
                            "alias_used": "кирилл",
                        })
                    continue
            names.append({
                "value": info,
                "span": match.span()
            })

    return names

def _find_conflicts(names: List[Dict]) -> Optional[List[int]]:
    """Check if there are name conflicts (multiple Kirills without disambiguation)."""
    kirill_ids = _get_kirill_ids()
    if len(kirill_ids) <= 1:
        return None  # Только один Кирилл - нет конфликта

    # Проверяем: если кто-то из names имеет alias_used "кирилл" (общий алиас)
    # значит использован неоднозначный алиас и нужен выбор
    for name_entry in names:
        alias_used = name_entry.get("alias_used", "")
        if alias_used == "кирилл":
            return list(kirill_ids)
    return None

def _create_span_distance(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """Calculate minimal distance between two spans."""
    return min(abs(a[1] - b[0]), abs(b[1] - a[0]))


def _parse_trainer_message_by_lines(
    text: str,
    disambiguation_map: Optional[Dict[str, int]] = None
) -> Optional[List[Dict]]:
    """
    Parse line-oriented schedules where one time applies to every name on a line.

    Example: "19.15 Колод Маккинли Зельдин" assigns 19:15 to all three.
    """
    current_date = _get_today_date()
    trainings: List[Dict] = []
    saw_schedule_line = False

    for raw_line in text.splitlines():
        line = _normalize_input(raw_line)
        if not line:
            continue

        names = _extract_names(line, disambiguation_map=disambiguation_map)
        conflict = _find_conflicts(names)
        if conflict and (not disambiguation_map or "кирилл" not in disambiguation_map):
            return [{"conflict": "kirill", "ids": conflict}]

        dates, invalid_date = _extract_dates(line, names, allow_same_day_weekday=True)
        if invalid_date:
            return None
        if dates:
            current_date = dates[0][0]

        if not names:
            continue

        times = _extract_times_from_text(line)
        date_spans = [span for _, span in dates]
        times = [
            item for item in times
            if not any(
                item[1][0] >= date_span[0] and item[1][1] <= date_span[1]
                for date_span in date_spans
            )
        ]

        # Multiple times on one line need the general name-to-time parser.
        if len(times) != 1:
            return None

        saw_schedule_line = True
        line_time = times[0][0]
        used_ids = set()
        for name_entry in names:
            name_info = name_entry["value"]
            if name_info["id"] in used_ids:
                continue
            used_ids.add(name_info["id"])
            trainings.append({
                "date": current_date,
                "time": line_time,
                "telegram_id": name_info["id"],
                "name": name_info["name"],
            })

    return trainings if saw_schedule_line and trainings else None


def parse_trainer_message(text: str, disambiguation_map: Optional[Dict[str, int]] = None) -> Optional[List[Dict]]:
    """
    Parse trainer's scheduling message block by block.
    """
    line_trainings = _parse_trainer_message_by_lines(
        text,
        disambiguation_map=disambiguation_map
    )
    if line_trainings:
        return line_trainings

    normalized_text = _normalize_input(text)
    explicit_date_match = _extract_date_from_text(normalized_text, [])
    explicit_date_span = explicit_date_match[1] if explicit_date_match and explicit_date_match[0] != "INVALID_DATE" else None
    
    # Split text into blocks (by athlete names)
    aliases = _get_athlete_aliases()
    sorted_aliases = sorted(aliases.keys(), key=len, reverse=True)
    name_pattern = r'\b(' + '|'.join(re.escape(a) for a in sorted_aliases) + r')\b'
    
    # Find all name occurrences to split the text into segments
    name_matches = list(re.finditer(name_pattern, normalized_text, re.IGNORECASE))
    
    if not name_matches:
        return None

    # Check for Kirill conflict in the whole message first
    all_names_info = _extract_names(normalized_text, disambiguation_map=disambiguation_map)
    kirill_conflict = _find_conflicts(all_names_info)
    if kirill_conflict and (not disambiguation_map or "кирилл" not in disambiguation_map):
        return [{"conflict": "kirill", "ids": kirill_conflict}]

    trainings = []
    pending_names = [] # Names waiting for a time
    current_date = _get_today_date()
    current_time = None

    # We'll split the text into blocks (by athlete names)
    aliases = _get_athlete_aliases()
    sorted_aliases = sorted(aliases.keys(), key=len, reverse=True)
    name_pattern = r'\b(' + '|'.join(re.escape(a) for a in sorted_aliases) + r')\b'
    
    # Find all name occurrences to split the text into segments
    name_matches = list(re.finditer(name_pattern, normalized_text, re.IGNORECASE))
    
    if not name_matches:
        return None

    # Check for Kirill conflict in the whole message first
    all_names_info = _extract_names(normalized_text, disambiguation_map=disambiguation_map)
    kirill_conflict = _find_conflicts(all_names_info)
    if kirill_conflict and (not disambiguation_map or "кирилл" not in disambiguation_map):
        return [{"conflict": "kirill", "ids": kirill_conflict}]

    # We'll split the text into blocks. Each block starts with an athlete's name.
    # The text BEFORE the first name might contain a date/weekday.
    header_text = normalized_text[:name_matches[0].start()]
    header_dates, _ = _extract_dates(header_text, [], allow_same_day_weekday=True)
    if header_dates:
        current_date = header_dates[0][0]
    
    header_times = _extract_times_from_text(header_text)
    if header_times:
        current_time = header_times[0][0]

    for i, match in enumerate(name_matches):
        name_alias = match.group(1).lower()
        name_info = aliases[name_alias]
        
        # Start of current block is either the end of the previous name or start of message
        prev_name_end = name_matches[i-1].end() if i > 0 else 0
        # End of current block is the start of the next name or end of message
        next_name_start = name_matches[i+1].start() if i+1 < len(name_matches) else len(normalized_text)
        
        # The content for THIS athlete
        block_text = normalized_text[prev_name_end:next_name_start]
        
        # Within this block, look for a new date/weekday
        block_dates, _ = _extract_dates(block_text, [], allow_same_day_weekday=True)
        if block_dates:
            current_date = block_dates[0][0]
            
        # Extract all times within THIS block only
        block_times = _extract_times_from_text(block_text)
        if explicit_date_span:
            block_times = [
                item for item in block_times
                if not (
                    prev_name_end + item[1][0] >= explicit_date_span[0]
                    and prev_name_end + item[1][1] <= explicit_date_span[1]
                )
            ]
        
        best_time = None
        if block_times:
            # Associate with the time closest to the name in THIS block
            min_dist = float('inf')
            for t_val, (t_start_rel, t_end_rel) in block_times:
                t_start_glob = prev_name_end + t_start_rel
                t_end_glob = prev_name_end + t_end_rel
                
                if t_start_glob >= match.end():
                    dist = t_start_glob - match.end()
                elif t_end_glob <= match.start():
                    dist = match.start() - t_end_glob
                else:
                    dist = 0
                
                if dist < min_dist:
                    min_dist = dist
                    best_time = t_val
            
            if best_time:
                # If we found a time in this block, apply it to all pending names too
                for p_name_info, p_date in pending_names:
                    trainings.append({
                        "date": p_date,
                        "time": best_time,
                        "telegram_id": p_name_info['id'],
                        "name": p_name_info['name']
                    })
                pending_names = []
                current_time = best_time

        if best_time or current_time:
            # Use found time or carried over time
            target_time = best_time or current_time
            trainings.append({
                "date": current_date,
                "time": target_time,
                "telegram_id": name_info['id'],
                "name": name_info['name']
            })
        else:
            # No time yet, add to pending
            pending_names.append((name_info, current_date))

    return trainings if trainings else None


def format_trainer_parsed_message(trainings: List[Dict]) -> str:
    """Format parsed trainings for trainer confirmation message."""
    lines = ["📋 Вот как я понял расписание:\n"]
    for t in trainings:
        date_str = t.get('date', '??.??')
        lines.append(f"• {t['name']} — {date_str} в {t['time']}")
    return "\n".join(lines)

def get_unparseable_warning(text: str) -> str:
    """Generate warning message for unparseable input."""
    return (
        "⚠️ Мне не удалось понять сообщение. Попробуйте использовать формат:\n"
        "• 14:00 Костя\n"
        "• 14.00 Костя, Настя\n"
        "• 11.05 Костя 14:00 (если нужна другая дата)\n\n"
        "Напишите время и имя спортсмена"
    )
