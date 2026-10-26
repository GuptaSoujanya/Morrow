"""Completion-based learning activity, using the local date recorded with each event."""
from __future__ import annotations

import datetime as dt

POINTS = {'course': 20, 'research': 10, 'dsa': 50}
BADGES = (
    ('first-step', 'First spark', 'Complete your first learning activity.', 'total', 1),
    ('three-days', 'Finding rhythm', 'Learn on 3 consecutive days.', 'best', 3),
    ('seven-days', 'Week of learning', 'Learn on 7 consecutive days.', 'best', 7),
    ('thirty-days', 'A lasting habit', 'Learn on 30 consecutive days.', 'best', 30),
    ('dsa-five', 'Pattern finder', 'Complete 5 different daily DSA topics.', 'dsa', 5),
    ('century', 'Curious mind', 'Record 100 learning completions.', 'total', 100),
)


def summary(data, today=None):
    today = today or dt.date.today()
    by_day = {}
    for event in data['history']:
        if event['action'] != 'completed':
            continue
        # Keep the calendar date at completion, including its recorded UTC offset.
        date = dt.datetime.fromisoformat(event['at']).date()
        if date > today:
            continue
        bucket = by_day.setdefault(date, {})
        bucket.setdefault((event['kind'], event['id']), {
            'id': event['id'], 'kind': event['kind'], 'title': event['title'],
            'xp': POINTS[event['kind']],
        })
    values = {'total': 0, 'best': 0, 'dsa': 0}
    earned, dsa_topics = {}, set()
    run, last, xp = 0, None, 0
    for date in sorted(by_day):
        run = run + 1 if last and date == last + dt.timedelta(days=1) else 1
        last = date
        values['best'] = max(values['best'], run)
        values['total'] += len(by_day[date])
        xp += sum(item['xp'] for item in by_day[date].values())
        dsa_topics.update(item['id'] for item in by_day[date].values() if item['kind'] == 'dsa')
        values['dsa'] = len(dsa_topics)
        for key, _, _, metric, target in BADGES:
            if values[metric] >= target:
                earned.setdefault(key, date.isoformat())
    current, cursor = 0, today if today in by_day else today - dt.timedelta(days=1)
    while cursor in by_day:
        current += 1
        cursor -= dt.timedelta(days=1)
    start = today - dt.timedelta(days=364)
    calendar_start = start - dt.timedelta(days=start.weekday())
    days = []
    for offset in range((today - calendar_start).days + 1):
        date = calendar_start + dt.timedelta(days=offset)
        items = list(by_day.get(date, {}).values())
        days.append({'date': date.isoformat(), 'count': len(items), 'level': min(4, len(items)), 'items': items})
    return {
        'date': today.isoformat(), 'start': calendar_start.isoformat(), 'days': days,
        'current_streak': current, 'best_streak': values['best'], 'today_count': len(by_day.get(today, {})),
        'active_days': sum(date >= start for date in by_day), 'total_completions': values['total'],
        'xp': xp, 'level': xp // 100 + 1, 'level_progress': xp % 100, 'dsa_topics': values['dsa'],
        'badges': [{'id': key, 'name': name, 'description': description, 'target': target,
                    'progress': min(values[metric], target), 'earned_at': earned.get(key)}
                   for key, name, description, metric, target in BADGES],
    }
