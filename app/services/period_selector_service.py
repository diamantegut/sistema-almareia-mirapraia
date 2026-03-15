from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set


class PeriodSelectorService:
    WEEKDAY_MAP = {
        'sun': 6,
        'sunday': 6,
        'domingo': 6,
        'dom': 6,
        'mon': 0,
        'monday': 0,
        'segunda': 0,
        'seg': 0,
        'tue': 1,
        'tuesday': 1,
        'terca': 1,
        'terça': 1,
        'ter': 1,
        'wed': 2,
        'wednesday': 2,
        'quarta': 2,
        'qua': 2,
        'thu': 3,
        'thursday': 3,
        'quinta': 3,
        'qui': 3,
        'fri': 4,
        'friday': 4,
        'sexta': 4,
        'sex': 4,
        'sat': 5,
        'saturday': 5,
        'sabado': 5,
        'sábado': 5,
        'sab': 5,
    }

    @staticmethod
    def parse_date(value: Any) -> datetime:
        text = str(value or '').strip()
        if not text:
            raise ValueError('Data obrigatória')
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(text)

    @classmethod
    def normalize_weekdays(cls, weekdays: Optional[List[Any]]) -> List[str]:
        if not weekdays:
            return []
        normalized: List[str] = []
        seen: Set[str] = set()
        for item in weekdays:
            key = str(item or '').strip().lower()
            if key not in cls.WEEKDAY_MAP:
                continue
            canonical = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][cls.WEEKDAY_MAP[key]]
            if canonical in seen:
                continue
            seen.add(canonical)
            normalized.append(canonical)
        return normalized

    @classmethod
    def expand_dates(cls, start_date: Any, end_date: Any, weekdays: Optional[List[Any]] = None) -> List[str]:
        start = cls.parse_date(start_date).date()
        end = cls.parse_date(end_date).date()
        if end < start:
            start, end = end, start
        normalized_weekdays = cls.normalize_weekdays(weekdays)
        allowed: Optional[Set[int]] = None
        if normalized_weekdays:
            allowed = {cls.WEEKDAY_MAP[w] for w in normalized_weekdays}
        out = []
        current = start
        while current <= end:
            if allowed is None or current.weekday() in allowed:
                out.append(current.isoformat())
            current += timedelta(days=1)
        return out

    @classmethod
    def parse_payload(cls, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = payload or {}
        start_date = str(data.get('start_date') or '').strip()
        end_date = str(data.get('end_date') or '').strip() or start_date
        weekdays = cls.normalize_weekdays(data.get('weekdays') or [])
        dates = cls.expand_dates(start_date, end_date, weekdays)
        return {
            'start_date': start_date,
            'end_date': end_date,
            'weekdays': weekdays,
            'dates': dates,
        }
