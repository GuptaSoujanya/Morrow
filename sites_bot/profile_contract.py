"""Deterministic inputs and reconciliation rules for every profile updater.

The language model may choose wording and navigate a board. It cannot change the
source of factual values, silently omit planned entries, or approve duplicate IDs.
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Any, Dict, List


def key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def protected(name: str) -> bool:
    if re.match(r'^(?:project|employment|experience|education|certification|skills?)\s*:', name, re.I):
        return False
    return bool(re.search(r"\b(?:photo|picture|password|privacy|pronouns|gender|diversity|marital|"
                          r"date of birth|email|phone|contact info|open to work|visibility|"
                          r"public profile|featured|services|profile language)\b", name, re.I))


def exclusion_reason(profile: Any, name: str) -> str:
    """User-selected exclusions apply to planning, editing, and verification."""
    if re.match(r'^(?:project|employment|experience|certification)\s*:', name, re.I):
        return ''
    preferences = (getattr(profile, 'extra_facts', {}) or {}).get('profile_update_preferences', {})
    if not isinstance(preferences, dict):
        return ''
    if preferences.get('skip_profile_photo') is True and re.search(r'\b(?:photo|picture)\b', name, re.I):
        return 'Profile photo skipped at the user\'s request.'
    if preferences.get('skip_school_education') is True and re.search(
            r'\b(?:school education|class\s+(?:xii|xi|x|12|10)|10th|12th|secondary(?: school)? education)\b', name, re.I):
        return 'School education skipped at the user\'s request; college education remains in scope.'
    return ''


def fact_edits(profile: Any, board: str) -> List[Dict[str, str]]:
    """Atomic facts: a combined salary/location edit must not mask a wrong value."""
    if profile is None:
        return []
    fields = [("Current location", "current_location", ""),
              ("Total experience", "total_experience_years", " years"),
              ("Current salary", "current_ctc_lpa", " LPA"),
              ("Expected salary", "expected_ctc_lpa", " LPA"),
              ("Notice period", "notice_period_days", " days")]
    # LinkedIn exposes current location, but no compensation/notice/total-experience editors.
    if board == "linkedin":
        fields = fields[:1]
    edits = []
    for label, attr, unit in fields:
        if board == "instahyre" and attr == "expected_ctc_lpa":
            continue
        value = getattr(profile, attr, None)
        if value is None or value == "":
            edits.append({"name": label, "action": "skip", "target": "", "current": "",
                          "why": "needs input: profile.yaml has no %s" % attr, "fact_key": attr})
            continue
        if unit:
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                raise ValueError("profile.yaml %s must be numeric" % attr) from None
            if not number.is_finite() or number < 0 or isinstance(value, bool):
                raise ValueError("profile.yaml %s must be a nonnegative finite number" % attr)
        precision = ''
        if attr == 'total_experience_years':
            months = round(Decimal(str(value)) * 12)
            precision = (' This is decimal years: use %d years and %d months in separate selectors. '
                         'Do not interpret the decimal digits as months. If the site only accepts whole years, '
                         'report that limitation instead of claiming an exact match.') % divmod(months, 12)
        edits.append({"name": label, "action": "update", "target": str(value) + unit,
                      "current": "", "why": "Authoritative value from profile.yaml: %s. Verify this exact fact; "
                      "if its editor needs missing facts, report needs_input." % attr + precision, "fact_key": attr})
    return edits


_LABELS = {
    'current_location': r'(?:current\s+location|currently\s+located\s+in|\blocationOt\b)',
    'total_experience_years': r'(?:(?:total|overall)\s+(?:(?:work|professional)\s+)?experience(?:\s+of)?|\bexperienceOneTheme\b)',
    'current_ctc_lpa': r'(?:(?:annual\s+)?current\s+(?:annual\s+)?(?:salary|ctc|compensation)|\bwalletOneTheme\b)',
    'expected_ctc_lpa': r'(?:annual\s+)?expected\s+(?:annual\s+)?(?:salary|ctc|compensation)',
    'notice_period_days': r'(?:notice\s+period|can\s+start\s+working)',
}
_NUMBER = r'\d[\d,]*(?:\.\d+)?'


def fact_key(name: str) -> str:
    if re.match(r'^(?:employment|experience|project|education|certification)\s*:', name, re.I):
        return ''
    matches = [field for field, pattern in _LABELS.items() if re.search(pattern, name, re.I)]
    return matches[0] if len(matches) == 1 else ''


def verify_fact(field: str, target: str, page: str):
    """Check a labelled fact with explicit units, never a number elsewhere on the page.

    A missing label or unsupported board rendering is unconfirmed, not success.
    This intentionally refuses to equate 16 LPA with 1.6 lakh or 2.9 with 2.5.
    """
    pattern = _LABELS.get(field)
    if not pattern or not target or not page:
        return None, []
    values = []
    for match in re.finditer(pattern + r'\s*[:*\-]?\s*', page, re.I):
        value = page[match.end():match.end() + 110]
        # Stop before a neighbouring fact; desired salary/locations cannot
        # satisfy current salary/location when cards are flattened to text.
        value = re.split('|'.join(_LABELS.values()), value, maxsplit=1, flags=re.I)[0]
        values.append(value)
    if field == 'current_location':
        city = key(target.split(',')[0])
        aliases = {'gurugram', 'gurgaon'} if city in {'gurugram', 'gurgaon'} else {city}
        if not values:
            # LinkedIn's own intro card leaves the city unlabelled. Its contact
            # overlay link anchors this value; city names in About/jobs do not.
            for alias in aliases:
                if re.search(r'\b' + re.escape(alias) + r',\s*[^,·\n]{1,60},\s*India\s*·\s*'
                             r'https://(?:www\.)?linkedin\.com/in/[^/\s]+/overlay/contact-info/', page, re.I):
                    return True, []
            return None, []
        found = any(re.match(r'^(?:edit\s+)?' + re.escape(alias) + r'\b', key(v))
                    for v in values for alias in aliases)
        return found, [] if found else [target]
    if not values:
        return None, []
    expected = Decimal(re.search(_NUMBER, target).group().replace(',', ''))
    for value in values:
        number = re.search(_NUMBER, value)
        if not number:
            if field == 'notice_period_days' and expected == 0 and re.search(r'\bimmediate\b', value, re.I):
                return True, []
            continue
        actual = Decimal(number.group().replace(',', ''))
        tail = value[number.end():]
        if field.endswith('_ctc_lpa'):
            if re.match(r'\s*(?:lpa|lakhs?|lacs?)\b', tail, re.I):
                pass
            elif re.search(r'₹|\bINR\b|rupees', value, re.I) or re.match(r'\s*(?:per annum|/year|annually)', tail, re.I):
                actual /= 100000
            else:
                continue  # A number without salary units is not proof.
        elif field == 'notice_period_days':
            if re.match(r'\s*months?\b', tail, re.I):
                continue  # Never silently equate a calendar month with 30 days.
            if not re.match(r'\s*days?\b', tail, re.I):
                continue
        elif field == 'total_experience_years':
            months = re.match(r'\s*years?\s+(\d+)\s*months?', tail, re.I)
            if months:
                # Compare the board's integer months to the explicitly saved
                # decimal years, rounded once, not truncated to whole years.
                if actual * 12 + int(months.group(1)) == round(expected * 12):
                    return True, []
                continue
            if not re.match(r'\s*(?:years?|yrs?)\b', tail, re.I):
                continue
        if actual == expected:
            return True, []
    return False, [target]


def project_date_edits(profile: Any, board: str) -> List[Dict[str, Any]]:
    """Dates need their own check even when a project's description already matches."""
    if board not in ('linkedin', 'naukri') or profile is None:
        return []
    edits = []
    for project in (getattr(profile, 'extra_facts', {}) or {}).get('projects_detail', []):
        if not isinstance(project, dict) or not project.get('name'):
            continue
        start, end = str(project.get('start', '')), str(project.get('end', ''))
        if not start or not end:
            continue  # Never infer dates from a matching description.
        name = str(project['name'])
        try:
            dates = [datetime.strptime(value, '%Y-%m') for value in (start, end)]
            if any(date.strftime('%Y-%m') != value for date, value in zip(dates, (start, end))) or dates[1] < dates[0]:
                raise ValueError('invalid timeline')
        except ValueError:
            edits.append(dict(name='Project dates: ' + name, action='skip', target='', current='',
                              why='needs review: invalid project start/end dates in profile.yaml'))
            continue
        edits.append(dict(name='Project dates: ' + name, action='update', current='',
                          target=' - '.join(date.strftime('%b %Y') for date in dates),
                          project_dates=dict(name=name, start=start, end=end),
                          why='Dates from the user-confirmed project facts. Edit the existing unique project in place, '
                              'preserving its description, skills and links. A matching description does not prove the dates. '
                              'If both dates already match, report already_ok without saving. Do not create another project.'))
    return edits


def verify_project_dates(project: Dict[str, str], page: str):
    """Read dates from this project's own LinkedIn/Naukri card, never its prose."""
    entries = re.split(r'https://(?:www\.)?linkedin\.com/in/[^/\s]+/details/projects/(?:edit/forms/\d+|\d+/edit)/\s*', page)
    name = re.escape(project['name'])
    month = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    date_range = re.compile(r'^\s*' + month + r'\s+(\d{4})\s*(?:-|–|—|to)\s*' + month + r'\s+(\d{4})\b', re.I)
    headers = []
    for entry in entries[1:]:
        title = re.match(name + r'(?=\s|$)', entry, re.I)
        if title:
            headers.append(entry[title.end():])
    # Naukri renders personal projects as title, edit icon, Self, and date range.
    for match in re.finditer(r'\b' + name + r'\s+editOneTheme\s+Self(?:\s*\((?:Offsite|Onsite)\))?\s+', page, re.I):
        headers.append(page[match.end():])
    outcomes = []
    for header in headers:
        match = date_range.match(header)
        if not match:
            outcomes.append(False)
            continue
        values = [datetime.strptime(match.group(m)[:3].title() + ' ' + match.group(y), '%b %Y').strftime('%Y-%m')
                  for m, y in ((1, 2), (3, 4))]
        outcomes.append(values == [project['start'], project['end']])
    return (all(outcomes), [] if all(outcomes) else ['project start/end dates']) if outcomes else (None, [])


def reconcile(edits: List[Dict[str, str]], profile: Any, board: str, plan: Any) -> List[Dict[str, str]]:
    """Keep factual targets and planned entities in the contract even if the LLM omits them."""
    result = [dict(e) for e in edits]
    if board == 'hirist' and plan is not None:
        for edit in result:
            if re.fullmatch(r'(?:about|profile summary|about / profile summary|about \(profile summary\))', edit['name'], re.I):
                edit['target'] = getattr(plan, 'short_summary', '')
                edit['why'] = 'Use the approved short summary in the 500-character About field.'
    for fact in fact_edits(profile, board):
        # Only replace an atomic field. A combined card remains an independent
        # task, with an explicit instruction that these atomic facts take priority.
        matches = [i for i, e in enumerate(result) if fact_key(e['name']) == fact['fact_key']]
        if len(matches) == 1:
            previous = result[matches[0]]
            result[matches[0]] = dict(fact, current=previous.get('current', ''))
        else:
            result.append(fact)
    if plan is not None:
        basics = [("Headline", getattr(plan, 'headline', '')),
                  ("Skills", ", ".join((getattr(plan, 'key_skills', []) or [])[:20 if board == 'instahyre' else 15 if board == 'hirist' else 100])),
                  ("About" if board == 'linkedin' else "Profile summary",
                   getattr(plan, 'about' if board == 'linkedin' else 'short_summary' if board == 'hirist' else 'summary', ''))]
        for name, target in basics:
            if target and not any(key(name) in key(e['name']) or key(e['name']) in key(name) for e in result):
                result.append(dict(name=name, target=target, action='update', current='',
                                   why='Required by the saved profile plan; inspect and update the existing section.'))
        for kind, entries in (("Project", getattr(plan, 'projects', []) or []),
                              ("Employment", getattr(plan, 'experience', []) or [])):
            for entry in entries:
                name = str(entry.get('name' if kind == 'Project' else 'company', '')).strip()
                if not name:
                    continue
                canonical = re.sub(r'\s*\(formerly[^)]*\)', '', name, flags=re.I)
                if any(key(canonical) in key(e['name']) for e in result):
                    continue
                target = str(entry.get('description') or entry.get('title') or name)
                if kind == 'Employment' and board in ('hirist', 'instahyre'):
                    target = ', '.join(str(entry.get(k, '')) for k in ('title', 'company', 'start', 'end') if entry.get(k))
                result.append(dict(name=kind + ': ' + name, target=target, action='update', current='',
                                   why='Inspect all existing entries first. Edit the unique match; add only after proving absence.'))
        for name in getattr(plan, 'certifications', []) or []:
            if not any(key(name) in key(e['name']) or 'certification' in key(e['name']) for e in result):
                result.append(dict(name='Certification: ' + name, target=name, action='update', current='',
                                   why='Inspect existing certificates by name, issuer and credential ID. Never invent dates.'))
        if profile is not None and not any('education' in key(e['name']) for e in result):
            result.append(dict(name='Education', target=profile.highest_qualification, current='',
                               action='update' if profile.highest_qualification else 'skip',
                               why='Verify education against the saved facts and resume.'))
    for edit in project_date_edits(profile, board):
        result = [previous for previous in result if key(previous['name']) != key(edit['name'])]
        result.append(edit)
    # Stable identity for retries: two differently labelled planner rows for the
    # same field must not result in two independent writes.
    unique = {}
    for edit in result:
        excluded = exclusion_reason(profile, edit['name'])
        if excluded:
            edit.update(action='skip', target='', why=excluded)
        identity = key(edit['name'])
        if identity in unique and unique[identity].get('target') != edit.get('target'):
            unique[identity].update(action='skip', why='needs review: conflicting targets for the same field')
        else:
            unique.setdefault(identity, edit)
    return list(unique.values())


def operation_id(board: str, edit: Dict[str, str]) -> str:
    value = json.dumps([board, key(edit['name']), edit.get('target', '')], ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def duplicates(entries: List[Dict[str, str]]) -> List[str]:
    """Repeated views of one ID are harmless; two IDs for one project/cert need review."""
    groups = {}
    for entry in entries:
        if entry.get('kind') not in ('projects', 'certifications'):
            continue
        identity = (entry['kind'], key(entry.get('name', '')))
        if identity[1] and entry.get('id'):
            groups.setdefault(identity, set()).add(entry['id'])
    return ['Duplicate %s: %s (%d distinct entries)' % (kind, name, len(ids))
            for (kind, name), ids in sorted(groups.items()) if len(ids) > 1]


_ENTRIES_JS = r"""
// Read identities, never infer duplicates from repeated page text/navigation.
const records = [];
for (const a of document.querySelectorAll('a[href]')) {
  const match = a.getAttribute('href').match(/\/details\/(projects|certifications)\/(?:(\d+)\/edit|edit\/forms\/(\d+))(?:\/|\?|$)/);
  if (!match) continue;
  const card = a.closest('li') || a.closest('[data-view-name="profile-component-entity"]');
  if (!card || !card.getClientRects().length) continue;
  const lines = card.innerText.split('\n').map(x => x.trim()).filter(Boolean);
  const name = lines.find(x => !/^(edit|delete|remove)\b/i.test(x));
  if (name) records.push({kind: match[1], id: match[2] || match[3], name});
}
return records;
"""


def read_entries(driver: Any) -> List[Dict[str, str]]:
    try:
        rows = driver.execute_script(_ENTRIES_JS)
        return [r for r in rows if isinstance(r, dict) and all(isinstance(r.get(k), str)
                for k in ('kind', 'id', 'name'))] if isinstance(rows, list) else []
    except Exception:
        return []


def report_issues(report: Dict[str, Any]) -> List[str]:
    """Conservative vetoes. Agent warnings may block success, never prove it."""
    issues = []
    rows = report.get('duplicates', [])
    if isinstance(rows, list):
        issues.extend('Duplicate needs review: ' + str(r)[:240] for r in rows if r)
    conflicts = report.get('conflicts', [])
    if isinstance(conflicts, list):
        issues.extend('Factual conflict: ' + str(r)[:240] for r in conflicts if r)
    reason = ' '.join(str(report.get(k, '')) for k in ('why', 'notes'))
    if re.search(r'(?:differs from|contradicts|conflicts with|does not match).{0,80}\b(?:facts|profile.yaml)\b', reason, re.I):
        issues.append('Factual conflict reported; compare the live profile with profile.yaml')
    for section in report.get('sections', []) or []:
        if not isinstance(section, dict):
            continue
        note = ' '.join(str(section.get(k, '')) for k in ('before', 'after', 'evidence', 'note'))
        mentions = list(re.finditer(r'\b(?:listed twice|appears? twice|duplicate(?:d)? entries)\b|\(two entries\)', note, re.I))
        affirmative = [m for m in mentions if not re.search(r'\b(?:no|without|zero)\s*$', note[max(0, m.start()-15):m.start()], re.I)]
        if affirmative:
            issues.append('Duplicate needs review: ' + str(section.get('name', 'entry')))
    return list(dict.fromkeys(issues))
