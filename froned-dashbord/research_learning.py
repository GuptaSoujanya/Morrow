"""Reading recommendations and explicit progress, using real saved material."""
import datetime as dt
import re

from common import learning_memory as memory
from pipeline.learning import split_days, week_of
from web import state


def saved():
    return memory.transact(state.APPLY, studied=state.STUDIED)


def plan_document(day):
    if not 1 <= day <= 90:
        raise ValueError("Choose a learning day between 1 and 90.")
    root = state.APPLY / ".research/learning"
    path = root / "weeks" / f"week-{week_of(day):02d}.md"
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Day {day} has no saved reading material yet. Generate the learning plan from Research agents.")
    text = split_days(path.read_text(encoding="utf-8")).get(day)
    if not text:
        raise ValueError(f"Day {day} is not in the saved learning plan yet.")
    title = re.sub(r"^## Day \d+\s*[:—-]?\s*", "", text.splitlines()[0]).strip()
    return {"id": f"plan/day-{day}", "key": f"plan/day-{day}", "day": day, "title": title,
            "category": "Learning", "path": path.relative_to(state.APPLY).as_posix(), "text": text, "file": path}


def document_info(identifier, items=None):
    match = re.fullmatch(r"plan/day-(\d{1,2})", identifier)
    if match:
        return plan_document(int(match[1]))
    if items is None:
        import dashboard_data
        items = dashboard_data.artifacts()["items"]
    item = next((item for item in items if item["id"] == identifier), None)
    if item is None:
        raise ValueError("This document is not available in the library.")
    info = {**item, "key": identifier, "day": None}
    if identifier.startswith("research/learning/daily/") or identifier == "research/learning/today.md":
        text = (state.APPLY / ".research" / item["path"]).read_text(encoding="utf-8")
        match = re.search(r"^#{1,2} .*?\bDay (\d+)\b", text[:1500], re.M)
        if match and 1 <= int(match[1]) <= 90:
            info["day"] = int(match[1])
            info["key"] = f"plan/day-{info['day']}"
    return info


def completion(info, data):
    return bool(data["documents"].get(info["key"], {}).get("done") or
                (info.get("day") is not None and info["day"] in data["plan"].get("done", [])))


def mark(identifier, done):
    if not isinstance(done, bool):
        raise ValueError("read must be true or false")
    info = document_info(identifier)
    memory.set_document(state.APPLY, info["key"], info["title"], done, info.get("day"))
    return {"ok": True, "read": done, "storage": ".memory/learning.json"}


def brief_document(item, data):
    if not item:
        return None
    path = state.APPLY / '.research' / item['path']
    text = path.read_text(encoding='utf-8')
    def plain(value):
        value = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', value)
        return re.sub(r'[*`#]', '', value).strip()
    headings = [plain(line[3:]) for line in text.splitlines() if line.startswith('## ')]
    if item['path'].endswith('04-tech-news.md'):
        headlines = [plain(line.split('**', 2)[1]) for line in text.splitlines() if line.startswith('**') and line.count('**') >= 2]
    else:
        headlines = headings
    paragraph = next((plain(line) for line in text.splitlines() if line.strip() and not line.startswith(('#', '|', '```', '- ', '*', '    '))), '')
    return {**item, 'read': completion(item, data), 'preview': headlines[:3], 'sections': len(headings), 'excerpt': paragraph[:240]}


def daily_research(items, data, selected):
    by_path = {item['path']: item for item in items}
    dated = sorted({item['path'].split('/')[1] for item in items if re.match(r'daily/\d{4}-\d{2}-\d{2}/', item['path'])}, reverse=True)
    folder = f'daily/{selected}/'
    definitions = [('digest', 'Daily digest', 'README.md', 'brief'), ('papers', 'Papers', '03-papers.md', 'brief:papers'),
                   ('tech', 'Tech radar', '04-tech-news.md', 'brief:tech-news'), ('companies', 'Company radar', '05-companies.md', 'brief:companies'),
                   ('goal', 'Daily learning goal', '01-goal.md', 'brief:goal'), ('design', 'System design deep dive', '02-system-design.md', 'brief:system-design')]
    sections = [{'key': key, 'title': title, 'group': group, 'path': '.research/' + folder + filename,
                 'document': brief_document(by_path.get(folder + filename), data)} for key, title, filename, group in definitions]
    known = {folder + filename for _, _, filename, _ in definitions}
    extra = [brief_document(item, data) for item in items if (item['path'].startswith(folder) and item['path'] not in known) or item['path'] == f'daily/{selected}.md']
    references = [brief_document(item, data) for item in items if '/' not in item['path']]
    return {'date': selected, 'available_dates': dated, 'latest': dated[0] if dated else None, 'sections': sections,
            'ready': sum(bool(section['document']) for section in sections), 'total': len(sections), 'additional': extra, 'references': references}


def summary(params=None):
    import dashboard_data
    params = params or {}
    data = saved()
    items = dashboard_data.artifacts()["items"]
    info = [document_info(item["id"], items) for item in items if item["id"].startswith("research/")]
    today = dt.date.today().isoformat()
    try:
        selected = dt.date.fromisoformat(str(params.get('date') or today)).isoformat()
    except ValueError:
        raise ValueError('Choose a research date in YYYY-MM-DD format.') from None
    done = data["plan"].get("done", [])
    day = next((n for n in range(1, 91) if n not in done), None)
    focus, missing = None, ""
    if day:
        try:
            entry = plan_document(day)
            focus = {key: value for key, value in entry.items() if key not in ("text", "file")}
            focus.update(read=False, caption=f"Day {day} of 90 · your next unfinished day")
        except ValueError as exc:
            missing = str(exc)
    briefings = sorted((i for i in info if re.match(r"daily/\d{4}-\d{2}-\d{2}/", i["path"])), key=lambda i: (i["path"].split('/')[1], i["path"].endswith(('README.md', 'overview.md'))), reverse=True)
    resume = sorted((i for i in info if re.match(r"resume-learning/\d{2}-", i["path"])), key=lambda i: i["path"])
    queue = [focus] if focus else []
    if briefings:
        latest = briefings[0]['path'].split('/')[1]
        item = next((i for i in briefings if i['path'].split('/')[1] == latest and not completion(i, data)), briefings[0])
        queue.append({**item, "read": completion(item, data), "caption": "Latest briefing · " + item["path"].split('/')[1]})
    remaining = next((i for i in resume if not completion(i, data)), None)
    if remaining:
        queue.append({**remaining, "read": False, "caption": "Resume deep dive · next unread topic"})
    completed_today = []
    completed_selected = []
    for kind, bucket in (("course", data["course"]), ("research", data["documents"])):
        for identifier, value in bucket.items():
            if value.get("done") and (value.get("completed_at") or "")[:10] == today:
                completed_today.append({"id": identifier, "kind": kind, **value})
            if value.get("done") and (value.get("completed_at") or "")[:10] == selected:
                completed_selected.append({"id": identifier, "kind": kind, **value})
    history = sorted(data["history"], key=lambda e: e["at"], reverse=True)
    size = 15
    pages = max(1, (len(history) + size - 1) // size)
    page = min(dashboard_data.integer(params.get("page"), 1, 1, 1000000), pages)
    courses = state.course_modules(state.COURSE)
    resume_index = next((i for i in info if i['path'] == 'resume-learning/README.md'), None)
    weeks = sorted((i for i in info if i['path'].startswith('learning/weeks/')), key=lambda i: i['path'])
    return {"date": today, "selected_date": selected, "focus": focus, "missing": missing, "queue": queue,
            "briefing": daily_research(info, data, selected),
            "resume": {'topics': [brief_document(i, data) for i in resume], 'index': brief_document(resume_index, data)},
            "weeks": [{**i, 'read': completion(i, data)} for i in weeks],
            "plan_done": len(done), "plan_total": 90, "plan_complete": len(done) == 90,
            "notes_read": len({i['key'] for i in info if completion(i, data)}), "notes_total": len({i['key'] for i in info}),
            "course_done": sum(data["course"].get(m.path, {}).get("done", False) for m in courses), "course_total": len(courses),
            "completed_today": sorted(completed_today, key=lambda e: e["completed_at"], reverse=True),
            "completed_selected_date": sorted(completed_selected, key=lambda e: e['completed_at'], reverse=True),
            "imported": [{"id": key, "kind": kind, **value} for kind in ("course", "documents") for key, value in data[kind].items() if value.get("imported") and value.get("done")],
            "legacy_plan_days": [n for n in done if f"plan/day-{n}" not in data["documents"]],
            "history": {"items": history[(page - 1) * size:page * size], "page": page, "pages": pages, "total": len(history), "size": size},
            "storage": ".memory/learning.json"}
