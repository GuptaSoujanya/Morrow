"""Spaced review of interview questions: what to recall today, and when to ask again.

The scheduler is the FSRS-4.5 core as ported in engram (nagisanzenin/engram,
scripts/engram.py), Copyright (c) 2026 nagisanzenin, MIT License; see
common/data/THIRD_PARTY_NOTICES.md. Each item keeps a stability s (days until
recall falls to 90%) and a difficulty d (1-10). A lower grade means a smaller s
and a nearer due date; a lapse collapses s, so weak questions come back soon.

State lives in user/memory/learning.json under `reviews` (id -> schedule) and an
append-only `review_log`; every function here mutates or reads that dict inside
the caller's learning_memory.transact and does no IO.

    python3 -m common.interview_review due
    python3 -m common.interview_review grade full_stack-3-1 good
"""
from __future__ import annotations

import datetime as dt
import math

RETENTION = 0.90
INTERVAL_MAX = 365
W = (0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
     1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755)
DECAY = -0.5
FACTOR = 19.0 / 81.0  # so that recall is 90% after s days
RATINGS = {'again': 1, 'hard': 2, 'good': 3, 'easy': 4}
# The weekly rubric's 0 / 1 / 2 (interview_practice.weekly_assessment).
RUBRIC = {'0': 'again', '1': 'hard', '2': 'good'}
# Engram's relearning dose: the 1st and 2nd reviews after first study come back
# within 3 and then 9 days, whatever s says, so new material gets spaced sessions.
DOSE_CAPS = (3, 9)


def _clamp(value, low, high):
    return max(low, min(high, value))


def retrievability(elapsed_days, stability):
    return (1.0 + FACTOR * elapsed_days / stability) ** DECAY if stability > 0 else 0.0


def interval_for(stability):
    days = stability / FACTOR * (RETENTION ** (1.0 / DECAY) - 1.0)
    return int(_clamp(round(days), 1, INTERVAL_MAX))


def _init_stability(g):
    return _clamp(W[g - 1], 0.1, 100.0)


def _init_difficulty(g):
    return _clamp(W[4] - (g - 3) * W[5], 1.0, 10.0)


def _next_difficulty(d, g):
    moved = d - W[6] * (g - 3)
    return _clamp(W[7] * _init_difficulty(3) + (1.0 - W[7]) * moved, 1.0, 10.0)


def _recall_stability(d, s, r, g):
    grow = (math.exp(W[8]) * (11.0 - d) * s ** -W[9] * (math.exp(W[10] * (1.0 - r)) - 1.0)
            * (W[15] if g == 2 else 1.0) * (W[16] if g == 4 else 1.0))
    return _clamp(s * (1.0 + grow), 0.1, 36500.0)


def _forget_stability(d, s, r):
    after = W[11] * d ** -W[12] * ((s + 1.0) ** W[13] - 1.0) * math.exp(W[14] * (1.0 - r))
    return _clamp(min(after, s), 0.1, 36500.0)  # a lapse never increases stability


def rating_of(value):
    rating = RUBRIC.get(str(value).strip(), str(value).strip().lower())
    if rating not in RATINGS:
        raise ValueError('Grade with again, hard, good or easy (or the rubric 0, 1, 2).')
    return rating


def track_of(item_id):
    if item_id.startswith('dsa:'):
        return 'dsa'
    return item_id.split('-', 1)[0]


def seed(data, item_ids, today):
    """Register new items as due tomorrow; items already scheduled are left alone."""
    reviews = data.setdefault('reviews', {})
    due = (today + dt.timedelta(days=1)).isoformat()
    for item_id in item_ids:
        reviews.setdefault(item_id, {'s': None, 'd': None, 'last': None, 'due': due,
                                     'reps': 0, 'lapses': 0, 'dose': True})


def grade(data, item_id, rating, today):
    """Apply one recall grade and book the next review; returns the new schedule."""
    rating = rating_of(rating)
    g = RATINGS[rating]
    reviews = data.setdefault('reviews', {})
    old = reviews.get(item_id) or {'reps': 0, 'lapses': 0, 'dose': True}
    s0, d0 = old.get('s'), old.get('d')
    if s0 is None:
        s, d, r = _init_stability(g), _init_difficulty(g), None
    else:
        s0 = _clamp(float(s0), 0.1, 36500.0)
        d0 = _init_difficulty(3) if d0 is None else float(d0)
        last = dt.date.fromisoformat(old['last']) if old.get('last') else today
        r = retrievability(max(0, (today - last).days), s0)
        d = _next_difficulty(d0, g)
        s = _forget_stability(d0, s0, r) if g == 1 else _recall_stability(d0, s0, r, g)
    days = interval_for(s)
    done = int(old.get('reps') or 0) - 1  # reviews completed since the first study
    if old.get('dose') and 0 <= done < len(DOSE_CAPS):
        days = min(days, DOSE_CAPS[done])
    new = {'s': round(s, 4), 'd': round(d, 4), 'last': today.isoformat(),
           'due': (today + dt.timedelta(days=days)).isoformat(),
           'reps': int(old.get('reps') or 0) + 1,
           'lapses': int(old.get('lapses') or 0) + (1 if g == 1 and s0 is not None else 0),
           'dose': bool(old.get('dose'))}
    reviews[item_id] = new
    data.setdefault('review_log', []).append(
        {'at': today.isoformat(), 'id': item_id, 'rating': rating, 'interval_days': days,
         'retrievability': None if r is None else round(r, 4)})
    return new


def due(data, today, limit=5):
    """Items due by today: most overdue first within a track, tracks taken in turn."""
    by_track = {}
    for item_id, entry in sorted(data.get('reviews', {}).items(), key=lambda kv: (kv[1]['due'], kv[0])):
        if dt.date.fromisoformat(entry['due']) <= today:
            by_track.setdefault(track_of(item_id), []).append(item_id)
    queues = [by_track[key] for key in sorted(by_track, key=lambda key: (data['reviews'][by_track[key][0]]['due'], key))]
    chosen = []
    while len(chosen) < limit and any(queues):
        for queue in queues:
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0))
    return chosen


def validate(data):
    """Raise ValueError when the saved review state is malformed."""
    reviews, log = data.get('reviews', {}), data.get('review_log', [])
    if not isinstance(reviews, dict) or not isinstance(log, list):
        raise ValueError('Invalid saved reviews. Your progress has not been reset.')
    try:
        for item_id, entry in reviews.items():
            if (not isinstance(item_id, str) or not isinstance(entry, dict)
                    or any(type(entry.get(key)) is not int or entry[key] < 0 for key in ('reps', 'lapses'))
                    or any(entry.get(key) is not None and not isinstance(entry[key], (int, float))
                           for key in ('s', 'd'))):
                raise ValueError()
            dt.date.fromisoformat(entry['due'])
            if entry.get('last') is not None:
                dt.date.fromisoformat(entry['last'])
        for event in log:
            if (not isinstance(event, dict) or not isinstance(event.get('id'), str)
                    or event.get('rating') not in RATINGS):
                raise ValueError()
            dt.date.fromisoformat(event['at'])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('Invalid saved reviews. Your progress has not been reset.') from exc


def question_text(item_id):
    """The question an id stands for, or the id itself when it is not in the bank."""
    from . import interview_practice
    return next((row['question'] for row in interview_practice.bank_rows() if row['id'] == item_id), item_id)


def main(argv=None):
    import argparse
    from pathlib import Path
    from . import learning_memory
    parser = argparse.ArgumentParser(prog='python3 -m common.interview_review')
    parser.add_argument('command', choices=('due', 'grade'))
    parser.add_argument('item', nargs='?')
    parser.add_argument('rating', nargs='?', help='again, hard, good or easy')
    args = parser.parse_args(argv)
    root, today = Path(__file__).resolve().parents[1], dt.date.today()
    if args.command == 'grade':
        if not args.item or not args.rating:
            parser.error('grade needs an item id and a rating')
        rating = rating_of(args.rating)
        result = {}
        learning_memory.transact(root, lambda data: result.update(grade(data, args.item, rating, today)))
        print('%s: %s, next review %s' % (args.item, rating, result['due']))
        return 0
    data = learning_memory.transact(root)
    for item_id in due(data, today, limit=20):
        print('%s  %s' % (item_id, question_text(item_id)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
