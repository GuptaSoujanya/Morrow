"""Bounded dashboard adapters for the project's real CLIs. No shell interpolation."""
import datetime as dt
import math
import re
from urllib.parse import urlsplit
from web import server, state

BOARDS = ('naukri', 'hirist', 'instahyre', 'cutshort', 'wellfound')
STAGES = ('learn', 'research:resume', 'profile:linkedin',
          *(f'{group}:{board}' for group in ('profile', 'apply') for board in BOARDS),
          *(f'brief:{key}' for key in ('goal','system-design','papers','tech-news','companies')))
GROUPS = ('', 'learn', 'profile', 'apply', 'brief', 'research', *STAGES)


def number(options, key, low, high, integer=True):
    raw = options.get(key)
    if raw in (None, ''):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f'{key.replace("_", " ")} must be a number.') from None
    if isinstance(raw, bool) or not math.isfinite(value) or not low <= value <= high or (integer and not value.is_integer()):
        raise ValueError(f'{key.replace("_", " ")} must be {"a whole number " if integer else ""}between {low} and {high}.')
    return str(int(value)) if integer else str(value)


def naukri_command(o, save=False):
    base = state.naukri_command(dry_run=server._on(o,'dry_run'), headless=server._on(o,'headless'),
        limit=server._limit(o), answer_mode=server._text(o,'answer_mode'),
        early_access=server._on(o,'early_access'), early_access_only=server._on(o,'early_access_only'),
        keywords=server._text(o,'keywords'), location=server._text(o,'location'))
    args=[]
    for key,low,high,integer in [('min_score',0,100,False),('max_days_old',0,365,True),('early_access_limit',1,500,True)]:
        value=number(o,key,low,high,integer)
        if value is not None: args += ['--'+key.replace('_','-'),value]
    llm=server._text(o,'llm_backend')
    if llm:
        if llm not in ('claude-cli','kiro-cli','anthropic','none'): raise ValueError('Choose a supported scoring provider.')
        args += ['--llm-backend',llm]
    return state.Command(base.label,(*base.argv,*args))


def profile_command(o, save=False):
    base=state.profile_command(dry_run=server._on(o,'dry_run'),if_due=server._on(o,'if_due'),headless=server._on(o,'headless'))
    return state.Command(base.label,(*base.argv,*(('--review',) if server._on(o,'review') else ())))


def linkedin_profile_command(o, save=False):
    return state.py('LinkedIn profile review','-m','linkedin_bot.update_profile',*(('--dry-run',) if server._on(o,'dry_run') else ()))


def cold_email_command(o, save=False):
    args=['-m','sites_bot.cold_email']
    for key,low,high in [('days',1,365),('pages',1,100),('limit',1,100)]:
        value=number(o,key,low,high)
        if value is not None: args += ['--'+key,value]
    to=server._text(o,'to')
    if to and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',to): raise ValueError('Enter a valid recipient email address.')
    url=server._text(o,'url')
    if url and (urlsplit(url).scheme not in ('http','https') or not urlsplit(url).netloc): raise ValueError('Use an http or https job URL.')
    for key in ('to','company','title','url'):
        value=server._text(o,key)
        if value: args += ['--'+key,value]
    for key in ('scan_naukri','dry_run'):
        if server._on(o,key): args.append('--'+key.replace('_','-'))
    return state.py('Recruiter email · '+('preview' if server._on(o,'dry_run') else 'save drafts'),*args)


def pipeline_command(o, save=False):
    command=str(o.get('command') or 'continue')
    if command not in ('continue','run','status','check','learn'): raise ValueError('Choose a supported pipeline command.')
    args=['-m','pipeline',command]
    group=str(o.get('group') or '')
    if group not in GROUPS: raise ValueError('Choose a supported pipeline group or stage.')
    if group: args += ['--only',group]
    skipped=o.get('skip') or []
    if isinstance(skipped,str): skipped=[x.strip() for x in skipped.split(',') if x.strip()]
    if not isinstance(skipped,list) or any(x not in GROUPS or not x for x in skipped): raise ValueError('Choose supported stages to skip.')
    for key in skipped: args += ['--skip',key]
    if server._on(o,'redo') and not group: raise ValueError('Select a stage or group before rerunning completed work.')
    if server._on(o,'done') and command != 'learn': raise ValueError('Mark done is only available for learning.')
    for key in ('dry_run','redo','fresh','done'):
        if server._on(o,key): args.append('--'+key.replace('_','-'))
    cli=server._text(o,'cli')
    if cli:
        if cli not in ('both','claude','kiro'): raise ValueError('Choose Claude, Kiro, or both.')
        args += ['--cli',cli]
    agents=number(o,'agents',1,8)
    if agents is not None: args += ['--agents',agents]
    bots=number(o,'bots',1,6)
    if server._on(o,'containers'):
        if bots is not None: raise ValueError('Containers run every site at once; leave bots at once empty.')
        # The dashboard shows the bots' screens itself, so the pipeline opens no page.
        args += ['--containers','--no-watch']
    elif bots is not None: args += ['--bots',bots]
    day=server._text(o,'date')
    if day:
        try: dt.date.fromisoformat(day)
        except ValueError: raise ValueError('Use a date in YYYY-MM-DD format.') from None
        args += ['--date',day]
    return state.py('Daily pipeline · '+command,*args)
