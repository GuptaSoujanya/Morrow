"""Read-only dashboard records and generated material, backed by the existing project."""
import datetime as dt
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlsplit
from web import state

SUBMITTED = {'applied','applied_platform','applied_external'}
BOARDS = {'all','naukri','hirist','instahyre','cutshort','wellfound','external'}


def shown_path(path):
    path = Path(path)
    return path.relative_to(state.APPLY).as_posix() if path.is_relative_to(state.APPLY) else path.name


def file_metadata(path, category, title, href):
    stat = path.stat()
    return {'title': title, 'category': category, 'path': shown_path(path), 'href': href,
            'bytes': stat.st_size,
            'updated_at': dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec='seconds')}


def resume_files():
    root = state.RESUMES
    if not root.is_dir(): return []
    return sorted(path for path in root.rglob('*.pdf')
                  if path.is_file() and path.resolve().is_relative_to(root.resolve()))


def resume_file(relative):
    path = state.RESUMES / relative
    if not relative or Path(relative).is_absolute() or '..' in Path(relative).parts or path not in resume_files():
        raise ValueError('Choose a saved resume PDF from Data hub.')
    return path


def inventory(input_files):
    """An explicit catalogue, never a recursive browser over credentials/session data."""
    sources, files = [], []
    def source(key, title, path, href, art, description):
        item = {'id': key, 'title': title, 'path': shown_path(path), 'href': href,
                'art': art, 'description': description, 'count': 0, 'exists': path.exists()}
        sources.append(item)
        return item
    db = state.database()
    for key, title, table, kind, description in [
        ('applications', 'Application attempts', 'applications', 'applications', 'Every recorded attempt and its outcome.'),
        ('jobs', 'Discovered jobs', 'jobs_seen', 'jobs', 'Unique opportunities collected by your bots.')]:
        item = source(key, title, db, '#/records/' + quote(kind+'/all/0', safe=''), 26, description)
        try:
            result = state._query(db, f'SELECT COUNT(*) AS total FROM {table}')
            item['count'] = result[0]['total'] if result else 0
        except (sqlite3.Error, OSError): item.update(count=None, error='The ledger could not be read. Try refreshing.')
    research = source('research', 'Research notes', state.APPLY/'.research', '#/research', 25, 'Briefings, learning plans and deep dives.')
    try:
        for item in artifacts()['items']:
            is_research = item['id'].startswith('research/')
            path = (state.APPLY/'.research' if is_research else state.REPORTS)/item['path']
            files.append(file_metadata(path, 'Research' if is_research else 'Drafts', item['title'], '#/research/'+quote(item['id'], safe='')))
            if is_research: research['count'] += 1
    except OSError: research['error'] = 'Some research files could not be read.'
    reports = source('reports', 'Daily reports', state.REPORTS, '#/reports', 29, 'Saved summaries of your application activity.')
    try:
        for path in state.REPORTS.glob('*/report.md'):
            if not path.is_file() or not path.resolve().is_relative_to(state.REPORTS.resolve()): continue
            try: day = dt.date.fromisoformat(path.parent.name).isoformat()
            except ValueError: continue
            files.append(file_metadata(path, 'Reports', 'Report · '+day, '#/reports/'+day))
            reports['count'] += 1
    except OSError: reports['error'] = 'Some reports could not be read.'
    profiles = source('profile', 'Profile & answers', state.APPLY/'data/inputs', '#/files/profile', 20, 'The saved facts and answers your crew uses.')
    for key, title in [('profile','Your profile'),('answers','Screening answers'),('company_sites','Company follow-ups')]:
        path = input_files.get(key)
        try:
            if path and path.is_file():
                files.append(file_metadata(path, 'Profile', title, '#/files/'+key))
                profiles['count'] += 1
        except OSError: profiles['error'] = 'Some profile files could not be read.'
    resumes = source('resumes', 'Resume PDFs', state.RESUMES, '#/data/resumes', 21, 'Download your source and tailored resumes.')
    try:
        for path in resume_files():
            title = path.parent.name+' · '+path.stem if path.parent != state.RESUMES else path.stem
            files.append(file_metadata(path, 'Resumes', title, '/api/resume-file?file='+quote(path.relative_to(state.RESUMES).as_posix(), safe='')))
            resumes['count'] += 1
    except OSError: resumes['error'] = 'Some resume files could not be read.'
    checkpoint = state.APPLY/'.memory/progress.json'
    flows = source('flows', 'Flow checkpoint', checkpoint, '#/pipeline', 28, 'Recorded daily stages and their saved progress.')
    try:
        saved = read_json(checkpoint, {})
        flows['count'] = len(saved.get('days', {}))
        if checkpoint.is_file(): files.append(file_metadata(checkpoint, 'Automation', 'Flow checkpoint', '#/pipeline'))
    except (OSError, ValueError): flows.update(count=None, error='The saved checkpoint could not be read.')
    return {'sources': sources, 'files': sorted(files, key=lambda f:f['updated_at'], reverse=True),
            'updated_at': dt.datetime.now().astimezone().isoformat(timespec='seconds')}


def integer(value, default, low, high):
    try: number=int(str(default if value in (None,'') else value))
    except (TypeError,ValueError): raise ValueError('Use whole numbers for period and pagination.') from None
    if not low <= number <= high: raise ValueError(f'Value must be between {low} and {high}.')
    return number


def records(params, db=None, today=None):
    kind=params.get('kind','applications')
    if kind not in ('applications','jobs'): raise ValueError('Choose applications or jobs.')
    days=integer(params.get('days'),14,0,36500)
    page=integer(params.get('page'),1,1,1000000)
    size=integer(params.get('size'),20,1,100)
    board=params.get('board','all')
    if board not in BOARDS: raise ValueError('Choose a supported board.')
    query=str(params.get('q','')).strip().casefold()
    outcome=str(params.get('outcome','all'))
    sort=params.get('sort','recent')
    if sort not in ('recent','score'): raise ValueError('Choose recent or score sorting.')
    db=db or state.database()
    if kind=='applications':
        raw=state._query(db,'''SELECT a.id,a.job_id,COALESCE(NULLIF(a.url,''),j.url) AS url,
            COALESCE(NULLIF(a.title,''),j.title) AS title,COALESCE(NULLIF(a.company,''),j.company) AS company,a.status,a.detail,
            a.quota_consumed,a.at,j.score FROM applications a LEFT JOIN jobs_seen j ON j.job_id=a.job_id''')
    else:
        raw=state._query(db,'''SELECT j.job_id,j.url,j.title,j.company,j.source,j.first_seen AS at,j.last_seen,j.score,
            (SELECT a.status FROM applications a WHERE a.job_id=j.job_id ORDER BY a.at DESC,a.id DESC LIMIT 1) AS status
            FROM jobs_seen j''')
    today=today or dt.date.today()
    start=today-dt.timedelta(days=days-1) if days else None
    eligible=[]
    options=set()
    for row in raw:
        moment=state._moment(row['at'])
        if moment is None or moment.date()>today or (start and moment.date()<start): continue
        row['board']=state._board_of_job(row['job_id']) if kind=='applications' else state.source_parts(row.get('source') or '')[0]
        row['status']=row.get('status') or 'not_attempted'
        row['label']=state.OUTCOMES.get(row['status'],row['status'].replace('_',' ').capitalize())
        row['kind']='sent' if row['status'] in SUBMITTED else state._KINDS.get(row['status'],'skipped')
        row['at']=moment.isoformat()
        # The UI may only turn HTTP(S) source URLs into clickable links.
        url=str(row.get('url') or '')
        if urlsplit(url).scheme not in ('http','https') or not urlsplit(url).netloc: row['url']=''
        if board!='all' and row['board']!=board: continue
        options.add(row['status'])
        if outcome=='submitted' and row['status'] not in SUBMITTED: continue
        if outcome=='matched' and (row.get('score') is None or row['score'] < state._setting_number('MIN_SCORE',state.Settings.min_score)): continue
        if outcome not in ('all','submitted','matched') and row['status']!=outcome: continue
        if query and query not in ' '.join(str(row.get(k) or '') for k in ('title','company','detail','job_id')).casefold(): continue
        eligible.append(row)
    eligible.sort(key=lambda r:((r.get('score') if r.get('score') is not None else -1),r['at']) if sort=='score' else (r['at'],r.get('id',0),r['job_id']),reverse=True)
    count=len(eligible)
    pages=max(1,(count+size-1)//size)
    page=min(page,pages)
    return {'kind':kind,'days':days,'page':page,'pages':pages,'size':size,'total':count,
            'rows':eligible[(page-1)*size:page*size],'statuses':sorted(options),
            'updated_at':dt.datetime.now().astimezone().isoformat(timespec='seconds')}


def read_json(path, default):
    if not path.exists(): return default
    try:
        result=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(result,dict): raise ValueError('Expected a mapping.')
        return result
    except (ValueError,OSError): raise ValueError(f'{path.name} could not be read. The saved data has not been changed.') from None


def workspace():
    root=state.APPLY
    checkpoint=read_json(root/'.memory/progress.json',{})
    today=dt.date.today().isoformat()
    entry=checkpoint.get('days',{}).get(today,{})
    stages=entry.get('stages',{})
    plan=entry.get('plan',list(stages))
    learning=read_json(root/'.research/learning/progress.json',{})
    return {'date':today,'pipeline':{'total':len(plan),'done':sum(stages.get(k,{}).get('status')=='done' for k in plan),
        'stages':[{'name':key,**stages.get(key,{'status':'pending'})} for key in plan]},
        'learning_done':len(learning.get('done',[])), 'research_count':len(artifacts()['items']),
        'configured_boards':[key.strip() for key in (state._setting('PLATFORMS') or 'hirist,instahyre').split(',') if key.strip()]}


def artifacts():
    items=[]
    for prefix,root,pattern in [('research',state.APPLY/'.research','**/*.md'),('email',state.REPORTS,'*/emails/*.eml')]:
        if not root.is_dir(): continue
        for path in root.glob(pattern):
            resolved=path.resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.is_file(): continue
            relative=path.relative_to(root).as_posix()
            title=path.stem.replace('-',' ').replace('_',' ')
            if prefix=='research':
                for line in path.read_text(encoding='utf-8',errors='replace').splitlines()[:12]:
                    if line.startswith('# '): title=line[2:].strip();break
            category='Email drafts' if prefix=='email' else 'Learning' if relative.startswith('learning/') else 'Resume research' if relative.startswith('resume-learning/') else 'Briefing'
            items.append({'id':prefix+'/'+relative,'title':title,'category':category,'path':relative,
                'updated_at':dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec='seconds')})
    return {'items':sorted(items,key=lambda x:x['updated_at'],reverse=True)}


def artifact(identifier):
    prefix,sep,relative=str(identifier).partition('/')
    if not sep or prefix not in ('research','email'): raise ValueError('Choose a generated document.')
    root=(state.APPLY/'.research') if prefix=='research' else state.REPORTS
    path=(root/relative).resolve()
    allowed={item['id'] for item in artifacts()['items']}
    if identifier not in allowed or not path.is_relative_to(root.resolve()): raise ValueError('This document is not available in the library.')
    if prefix=='email':
        from email import policy
        from email.parser import BytesParser
        import html
        message=BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body=message.get_body(preferencelist=('plain',))
        text=body.get_content() if body else 'This draft has no plain-text body.'
        rendered=f'<h1>{html.escape(str(message.get("Subject", "Email draft")))}</h1><p>To: {html.escape(str(message.get("To", "")))}</p><pre>{html.escape(text)}</pre>'
    else:
        from markdown_it import MarkdownIt
        md=MarkdownIt('commonmark',{'html':False}).enable(['table','strikethrough'])
        tokens=md.parse(path.read_text(encoding='utf-8'))
        for token in tokens:
            for child in token.children or []:
                if child.type=='image':
                    child.type='text';child.content='[Image omitted]';child.children=None;child.tag='';child.attrs={}
                if child.type!='link_open': continue
                target=child.attrGet('href') or ''
                scheme=urlsplit(target).scheme
                if scheme in ('http','https','mailto'):
                    child.attrSet('target','_blank');child.attrSet('rel','noopener noreferrer')
                elif not scheme and not target.startswith('#'):
                    resolved=(path.parent/target.split('#')[0]).resolve()
                    if resolved.is_dir(): resolved=resolved/'README.md'
                    if resolved.is_relative_to(root.resolve()):
                        key='research/'+resolved.relative_to(root.resolve()).as_posix()
                        if key in allowed:
                            child.attrSet('href','/#/research/'+quote(key,safe=''));child.attrSet('target','_top')
                        else: child.attrSet('href','#')
                    else: child.attrSet('href','#')
                elif scheme: child.attrSet('href','#')
        rendered=md.renderer.render(tokens,md.options,{})
    return {'id':identifier,'title':path.stem,'html':rendered}
