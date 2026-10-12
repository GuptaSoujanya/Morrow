# Naukri-Autoapply-Bot

> Automation that applies to jobs on Naukri.com automatically for faster job hunting. Uses **Selenium** for browser automation and **BeautifulSoup** for parsing job listings.

## 📋 Features

- ✅ Automatically logs in to Naukri.com
- ✅ **Multi-tab parallel search** — Opens each keyword category in its own browser tab simultaneously
- ✅ Searches for jobs by keywords and location (updated for 2026 Naukri redesign)
- ✅ Visits job listings and clicks "Apply" / "Apply on company site"
- ✅ Handles custom first/last name fields and "Submit and Apply" flow
- ✅ Detects daily application quota limits
- ✅ Saves results (passed/failed) to a CSV file
- ✅ Uses **Microsoft Edge** browser
- ✅ Uses `webdriver-manager` for automatic driver download (no manual setup!)

## 🚀 How Multi-Tab Parallel Search Works

Instead of processing each keyword one-by-one (slow), the bot **opens every keyword search page in its own browser tab simultaneously**:

```
Keyword: "python developer"  → Tab 1 (Page 1) + Tab 2 (Page 2)
Keyword: "data analyst"     → Tab 3 (Page 1) + Tab 4 (Page 2)
Keyword: "software engineer" → Tab 5 (Page 1) + Tab 6 (Page 2)
...all open at the same time!
```

**Benefits:**
- ⚡ **Much faster** — all keyword searches load in parallel instead of waiting sequentially
- 📊 **More jobs found** — each keyword gets equal attention
- 🔄 **Smart deduplication** — duplicate job links across keywords are automatically removed before applying

## 🚀 Quick Start

### Prerequisites
- **Python 3.7+** installed on your system
- **Microsoft Edge** browser installed
- A valid **Naukri.com** account

### 1. Clone the repository

```bash
git clone https://github.com/lordzohar/Naukri-autoapply-bot.git
cd Naukri-autoapply-bot
```

### 2. Install dependencies

It's recommended to use a virtual environment:

```bash
# Create a virtual environment (optional but recommended)
python -m venv venv

# Activate it:
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 3. Configure your credentials

```bash
# Copy the example environment file
copy .env.example .env
```

Then edit **`.env`** (⚠️ NEVER commit this file) with your details:

```ini
# Your Naukri.com login credentials
NAUKRI_EMAIL=your_email@example.com
NAUKRI_PASSWORD=your_password

# Your personal details
FIRSTNAME=YourFirstName
LASTNAME=YourLastName

# Job search keywords (comma-separated)
KEYWORDS=python developer, data analyst, software engineer

# Location (leave empty for all locations, or specify a city like "bangalore", "mumbai", "remote")
LOCATION=bangalore

# Number of search result pages to scrape per keyword (default: 2)
PAGES_PER_KEYWORD=2

# Only return jobs whose experience range covers this many years (0 = off)
SEARCH_EXPERIENCE_YEARS=3

# Maximum applications per run (Naukri allows ~100/day)
MAX_APPLICATIONS=50
```

### 4. Run the bot

```bash
python Naukri-Edge.py
```

> **Note:** The script uses `webdriver-manager` to automatically download the correct EdgeDriver. No manual driver setup needed!

### 5. Check results

After running, results are saved to **`naukriapplied.csv`** with two columns:
- `passed` — URLs of jobs successfully applied to
- `failed` — URLs where the apply attempt failed

## 🖥️ Sandy: one screen for everything

Everything below can be run from one terminal screen, without remembering a single flag:

```bash
../sandy                  # from apply/, or the full path from anywhere
venv/bin/python -m sandy  # the same thing
```

Pick a section on the left (or press `1`-`9`, `0`), set its options, press **Run**, and watch
the output stream underneath. Each page shows the exact command it will run, so nothing is hidden.

| Section | What it runs |
|---|---|
| Today | What is waiting for you, plus one-press Apply now / Practice run / report / answers / today's study module |
| Apply on Naukri | `python -m naukri_bot` with practice run, limit, answer mode, Early Access, keywords, location |
| Company sites | `common.assist` for the waiting forms, `sites_bot.external --url ...` for one page |
| Naukri profile | `naukri_bot.update_profile`, schedule status, turn on the daily schedule |
| LinkedIn post | `linkedin_bot --dry-run / --propose / --post / --if-due` (publishing asks first) |
| Tailor resume | `common.resume --tailor`: paste the job description straight into the screen |
| Reports | Build a day's report and read it right there |
| Study | Read the course right in the terminal: today's module from the 8-week plan, every module by track with ✓ for the ones you marked read (kept in `reports/studied.json`). Also starts / stops the course site at http://localhost:8000, which keeps running after you quit |
| Your to-dos | The unanswered questions, blank facts and waiting company sites, with a built-in editor |
| Setup | Google sign-in for company sites, edit `.env`, install requirements, run the tests |

Keys: `x` stops a run (press again to force), `o` makes the output full height, `l` clears it,
`esc` goes back to the menu, `q` quits. In the editor, `ctrl+s` saves and `esc` closes.
In a course module, `n` / `p` turn to the next or previous module, `m` marks it read, `t` hides the
contents, `b` goes back after following a link, and `w` opens the page on the study site, where
the Mermaid diagrams are drawn (in the terminal they show as text).

## 🤖 naukri_bot (v2 — recommended)

`Naukri-Edge.py` and `Naukri-Recommended.py` above are the **legacy** scripts. They are kept
as-is and still work the way they always did. New work happens in the `naukri_bot/` package,
which exists because the legacy scripts could not answer three questions honestly:

1. *Did the application actually go through?* — a click that did not raise proves nothing.
2. *How much of my 50/day quota is left?* — "Apply on company site" leaves Naukri entirely
   and consumes zero quota, yet the legacy counter incremented for it.
3. *Is this job actually relevant to me?* — the legacy scripts ranked nothing; they took
   Naukri's own ordering, or whatever the keyword search happened to return.

### What it does

One command, once each morning:

```bash
python3 -m naukri_bot --dry-run   # show what it WOULD apply to, click nothing
python3 -m naukri_bot             # actually apply
```

It collects a large candidate pool from freshness-sorted keyword searches (keywords derived
from **your** resume) plus the recommended feed, scores every job against your resume and its
posting age, drops anything already applied to in a previous run, and then applies to the best
ones until the daily quota is spent.

### The rules it will not break

- **Nothing is reported as applied unless it is verified.** Login, apply, and questionnaire
  submission each have an explicit verification step.
- **Quota is debited only for confirmed Naukri-native applications.** An external redirect is
  recorded as skipped, not as an application.
- **Screening questions are answered only from facts you supplied.** If a question needs a fact
  that is not in your profile, the bot abandons that application rather than guessing. There is
  no fuzzy matching anywhere in the package — the legacy `fuzzy_lookup` could match
  "5 years" to "15 years" and submit the wrong answer to a real employer.
- **Ranking is ours, not Naukri's.**

### Setup

```bash
pip install -r requirements.txt
cp .env.example .env                          # credentials + tuning
mkdir -p data && cp naukri_bot/profile.example.yaml data/profile.yaml
```

Then fill in `data/profile.yaml`. Fields you leave blank are facts the bot **does not know** — it
will skip a job rather than invent a notice period or a salary expectation for you. The fields
that matter most are the ones a resume cannot supply: current CTC, expected CTC, notice period,
relocation willingness.

### LLM backend

Job scoring and screening answers use an LLM. By default it shells out to the `claude` CLI, so
**no API key is required**. Set `LLM_BACKEND=anthropic` (and `ANTHROPIC_API_KEY`) to use the SDK
instead, or `LLM_BACKEND=none` to run on lexical scoring alone — in that mode any screening
question that is not already in the answer cache will cause the bot to skip that job.

### Useful flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Rank and print the plan, then stop before the first click |
| `--limit N` | Apply to at most N jobs this run |
| `--min-score S` | Raise/lower the relevance floor (default 55) |
| `--max-days-old D` | Ignore postings older than D days (default 7) |
| `--keywords "a,b"` | Override resume-derived search keywords |
| `--answer-mode propose` | Log what it *would* answer, then skip — good for a first run |
| `--headless` | Run without a visible window (more likely to be challenged) |

`naukri_bot.db` holds your applied-history and quota memory. Deleting it makes the bot forget
what it already applied to and how much quota it has spent today — back it up, don't clear it.

### Keep your profile "recently updated"

Recruiter searches on Naukri rank profiles by how recently they were modified, so a profile
nobody touched for a week sinks. The updater (ported from the standalone naukri-auto-updater)
toggles a trailing `.` on your resume headline, which Naukri counts as an update, using the same
verified login and saved browser session as the apply run. It spends **none** of the apply quota.

```bash
python3 -m naukri_bot.update_profile --dry-run   # log in, open the editor, read it, change nothing
python3 -m naukri_bot.update_profile             # toggle the dot once, right now
```

The first run from a fresh browser profile is the only one that needs you at the keyboard:
Naukri sends an OTP to your registered mobile or email, and the run keeps the Chrome window open
for up to 5 minutes while you type it in. The session is then saved in `.browser-profile/` and
every later run, scheduled ones included, skips the login form. A headless run cannot wait for
you, so it exits with code 2 (and a Telegram alert, if configured) instead: do the first run
with a visible window.

The new headline is read back from the editor before Save is clicked and from the profile page
after it; nothing is reported as updated unless both checks pass. A failed run leaves a
screenshot in `screenshots/` and, if `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are set in `.env`,
sends you a Telegram message after the third failed attempt. `DRY_RUN` in `.env` only concerns
applications; the updater listens to its own `--dry-run` flag.

To run it three times a day (09:00, 13:30, 18:30 local time) on macOS:

```bash
./scripts/install_profile_updater.sh   # launchd agent that polls every 15 minutes
./scripts/profile_update_status.sh     # is it loaded, which slots ran today, last log lines
```

The agent runs `update_profile --if-due`, which only acts when a slot is due and not yet done,
so a laptop that was asleep at 09:00 and 13:30 catches up once when it wakes, not twice. Slot
memory lives in `logs/profile_update.json` and output in `logs/profile_update.log`. Uninstall
with `launchctl bootout gui/$(id -u)/com.naukri-bot.profile-update`.

Two things to know before scheduling it:

- **Keep the checkout outside `~/Desktop`, `~/Documents` and `~/Downloads`**, or grant the
  Python binary that `venv/bin/python` points at access to the folder under System Settings →
  Privacy & Security → Files and Folders. macOS blocks background launchd jobs from reading
  those folders, and the failure is a silent "Operation not permitted" in
  `logs/launchd-profile-update.err`. The install script warns when this applies.
- A scheduled run that overlaps your morning apply run cannot share the browser profile, so it
  falls back to a fresh session and logs in with `NAUKRI_EMAIL` / `NAUKRI_PASSWORD`. Start
  `python3 -m naukri_bot` well before 09:00 or after that slot has run.

### Your resume: edit the LaTeX, the bot does the rest

Keep your resume as LaTeX in `resume/base.tex` (the folder is gitignored because the file
carries your phone number and email) and point `RESUME_PATH` at it. The bot compiles it with
[tectonic](https://tectonic-typesetting.github.io/) (`brew install tectonic`; `pdflatex` and
`xelatex` also work, see `TEX_COMPILER`) and names the PDF after the name in the header, for
example `Soujanya_Gupta_Resume.pdf`, or whatever `RESUME_FILE_NAME` says.

```bash
python3 -m common.resume            # compile resume/base.tex -> resume/out/base/<name>.pdf
python3 -m common.resume --upload   # compile, then put the PDF on your Naukri profile
```

`--upload` reads the profile's resume card before and after, reloads the page, and only
reports success when the card shows the new file name with today's date. With
`UPLOAD_RESUME_DAILY=true` the profile updater does the same thing on its own: once a day at
the first slot, and again whenever you edit `base.tex` and the compiled PDF changes. So
updating your tech stack is: edit the `.tex`, save, done.

**Tailoring per application.** With `TAILOR_RESUME=true`, each real application (never a dry
run) first gets its own copy of the resume. The LLM may do exactly four things:

- reorder the items in each **Skills** line so the ones the posting asks for come first (an
  item that is added, dropped or renamed is rejected and the base order is kept);
- reorder the **bullet points** under each role so the most relevant one prints first (the
  words of a bullet never change; an order that drops or repeats a bullet is rejected);
- reword the one-line **subtitle** under your name;
- rewrite the **Summary** so the most relevant experience comes first, in your own words.

Every tool, employer, number and capitalised name in the rewritten text is checked against the
base resume; a proposal that mentions anything the resume does not already say is rejected and
the base text kept, as is anything with buzzwords, em dashes or exclamation marks. The result
is compiled and must fit in the same number of pages as the base, otherwise the base summary
is restored (and failing that, the base resume is used). The tailored PDF is uploaded to your
profile, the application is made with it, and the base PDF is put back at the end of the run,
even when the run stops with an error. The uploads happen in a second browser tab that stays on
your Naukri profile, while the first tab keeps the job pages, so you can watch each one.
Each job gets its own folder named after it, `resume/out/tailored/<Company - Role>/`
(for example `resume/out/tailored/Acme - AI Engineer/`), holding the PDF that was sent,
`posting.txt` (the job ad as it read that day), `tailored.tex` and a `tailoring.json` that
lists what changed and what was refused, so you can always read back what a recruiter received. Try it on a pasted posting first:

```bash
python3 -m common.resume --tailor posting.txt --title "AI Engineer" --company "Acme"
```

### Your data folder: the three files you edit

Everything the bot needs from you, and everything it could not do alone, lives in `data/`:

| File | What it holds | What you do |
|---|---|---|
| `data/profile.yaml` | Your facts: contact details, experience, CTC, notice period, education, links. | Fill the fields left `null`; the daily report lists them. |
| `data/answers.txt` | Your own answers to application questions, as `Q:` / `A:` blocks. | Write the answer after `A:` for every question the bot added. |
| `data/company_sites.md` | Company-site applications that stopped short of submitting, with the link, the resume to send and what is missing. | Finish them by hand, or answer the missing questions and let the next run retry. |
| `data/accounts.md` | Career sites the bot signed in to or made an account on, and with which email. | Nothing; read it to know where you have accounts. |

`answers.txt` is read before anything else, so your own words always win over the cache, the
profile and the model. Several `Q:` lines can share one `A:`; a question matches when it is the
same text, ignoring case and punctuation, or nearly so. For a dropdown the answer must name one of
its options. When a question cannot be answered from these files, the bot makes one honest
judgement (below) and otherwise does not guess: it adds the question to the end of `answers.txt`
with an empty `A:`, the job and the date, and the next run uses whatever you write there. The file is re-read whenever it changes, even during a run.

**The AI fills what your own files already answer.** Before and after every run (and on demand),
the model looks at each empty `A:` in `answers.txt` and each `null` in `profile.yaml` and answers
it from three sources only: your resume, your profile and the answers you have already written.
It must quote, word for word, the line that supports the answer, and the quote is checked against
the files; a number in the answer must appear in the quote. It never answers "why do you want to
join us", never claims years in a tool none of your files name, and never copies identity numbers.
Each filled line gets a `# AI filled this on <date> from your <file>: "<quote>"` comment above
it, the old file is kept in `data/backups/` (last 10), and the day's report lists every change.
A blank it could not answer is not asked again until one of your files changes.

It also compares the two files: when `answers.txt` and `profile.yaml` give different expected
CTC, notice period, serving-notice, passport, relocation or total experience, or the date of birth
is not a real date, the run log and the report say so. It does not pick a side; you fix it.

```bash
python3 -m common.assist --dry-run   # show what it would fill, change nothing
python3 -m common.assist             # fill, back up, record
```

**When nothing answers a question, the AI judges it (`JUDGE_ANSWERS=true`).** A screening
question that no file and no stated fact answers used to skip the whole job. Now, in `auto` mode,
the model gets a second look with your resume, profile, answers and the posting, and may answer
only with one of these honest inferences:

- a skill, tool or domain that none of your files name: **0** years (or the "none / less than a
  year" option), "No" to "have you worked with it";
- a skill your resume shows: the years of that role, never more than your total experience, with
  the resume line quoted;
- a follow-up whose premise your files make false ("If yes, share the employee code" when you never
  worked there): **N/A**;
- a list without your value: the range that contains your number, or "Other";
- a question your files answer in other words (a city you listed, a shift you declined), quoted.

Anything else stays blank for you. A number it types must be written in your files, a positive
claim must quote them, and gender, race, disability, visa, sponsorship, citizenship, the right to
work in a country, identity numbers and "why us" questions are never judged. A typed judgement is
written into `answers.txt` with `# AI judged this on <date> while applying to <role> at <company>:
<reason>. Change it if it is wrong.` above it, so the next job reads it from the file and your edit
replaces it. A pick from one form's list ("Other") is used for that application only. The day's
report lists every judgement under **Answered by judgement**.

### Company websites ("Apply on company site")

With `EXTERNAL_APPLY=true` the bot follows Naukri's company-site button for up to
`EXTERNAL_APPLY_LIMIT` jobs a run (never on a dry run) and works the employer's form:

1. Opens the site in a new tab and recognises the system behind it (Greenhouse, Lever, Ashby,
   Workable, SmartRecruiters, ...). It clicks through an "Apply" button when the form is behind one.
   A job-search box ("Keyword", "Location") is not taken for an application form. A removed posting
   ("this page was moved", "no longer available", a 404) is recorded as gone and kept off your list.
   When the page shows no form and no sign-in, the **page brain** takes a screenshot (kept in
   `screenshots/`), shows it with the page's text and a numbered list of its buttons and links to the
   local `claude` CLI, and acts on the answer: click one control that leads to this job's form (up
   to twice), call the posting gone, or stop. The model may only read that screenshot; the page's
   words are passed as data, never as instructions. A page with a captcha or "verify you are human"
   check is never sent to it: the screenshot is saved for you and the job goes to your list.
2. If the site wants an account (Workday, iCIMS, Taleo, SuccessFactors, company portals, or any
   page whose form is just an email and a password), it
   first tries **Sign in with Google** with `GOOGLE_EMAIL`. Each run makes sure the bot's browser
   is signed in to that Google account before the first company site: it types the email, then
   `GOOGLE_PASSWORD` if you set one (optional), and leaves a passkey, phone prompt or code to you,
   waiting 2 minutes. Once signed in, the session is kept and no run asks again. If Google answers
   "Couldn't sign you in", the bot stops asking for the rest of the day; sign in by hand with
   `scripts/google_login.sh` instead. Otherwise it signs in with `COMPANY_SITE_EMAIL`
   (default: `GOOGLE_EMAIL`, then `NAUKRI_EMAIL`) and `COMPANY_SITE_PASSWORD`, and when that
   fails or no password exists yet, it creates the account: email, the password twice, your name,
   the terms box. The first time a password is needed, a strong one is generated and written to
   `.env` as `COMPANY_SITE_PASSWORD`, so every site shares it. Every site it signs in to or
   registers on is listed in `data/accounts.md` (never the password). A dry run signs in with a
   saved password but never creates an account. A site that wants its email verified first, shows
   a captcha, or already has an account under your email with another password stops here and
   says which of those it was.
3. Fills the form page by page (Next, Continue, Save and Continue; up to 8 pages), skipping the
   hidden "robots only" boxes some sites plant. Name, email, phone, links, location and current
   role come from `data/profile.yaml`; every other
   question from `data/answers.txt`, then the profile, then the model, exactly as on Naukri;
   attaches the resume tailored for that job (or the base one); declines optional diversity
   questions; ticks the privacy consent and leaves other optional boxes ("Remember me", job alerts)
   alone. A **required** long-answer box ("Why this role?", a cover-letter text box) takes your
   answer from `answers.txt` if there is one; otherwise, with `JUDGE_ANSWERS=true`, one is written
   for that job from your resume and the posting only: first person, 2 to 4 sentences, checked so it
   names nothing the resume or posting does not and uses none of the usual filler words, and sent
   back once to be fixed if it does. Each one is kept in
   `resume/out/tailored/<Company - Role>/answers.md` and listed in the day's report.
4. Clicks Submit **only** when every required field is filled, and counts the application only when
   the site confirms it ("Thank you for applying", a confirmation page). A site that answers with an
   error is recorded as an error, never as applied.
5. Anything short of that, such as a question it cannot answer, a cover letter, a captcha, an
   email to verify, or a page the site will not let it leave, goes to `data/company_sites.md`,
   and the questions go to `data/answers.txt`. The tab is closed and the run carries on.
   LinkedIn and Indeed postings always go to the file: they need those networks' own logins.

Sign in to Google once, while no bot is running (either works):

```bash
python3 -m sites_bot.external --google-login   # the bot types your email; you finish the passkey or prompt
scripts/google_login.sh                         # plain Chrome on the bot's profile; sign in, then Cmd+Q
```

Work one page by hand, for example a link from `company_sites.md`:

```bash
python3 -m sites_bot.external --url "https://jobs.lever.co/acme/123" --title "AI Engineer" --company "Acme" --dry-run
```

`--dry-run` fills the form and finds Submit without clicking it, and the window stays visible so you
can look. Company-site applications use no Naukri quota and never count toward
`TARGET_APPLICATIONS`. Google may still ask "verify it's you" on some sites; when it does, the bot
waits two minutes for you in the window, then tries the email route.

### Browser agent: Claude Code takes over a stuck site

The scripted filler above knows the common forms. When a site beats it (an odd dropdown, a
Workday step it cannot find the resume upload on, a "Save and Continue" that does not move on),
`BROWSER_AGENT=true` hands that open page to **Claude Code**, signed in with your local `claude`
login, as a browser agent:

- `claude -p` starts with one MCP server, Playwright, attached over CDP to the bot's own Chrome.
  The sign-ins, cookies and the half-filled form carry over, and you can watch it work in the
  window. Its only tools are the browser tools: no shell, no file edits, no web fetch, no other
  MCP servers.
- Its task holds your facts (`profile.yaml`), your answers (`answers.txt`), your resume text, the
  posting, the tailored resume PDF to attach, and the same rules as the scripted filler: never
  invent an answer (an unanswered required question comes back to you as "needs you for: ..."),
  decline optional diversity questions, write a required "Why us?" in 2-3 sentences from the resume
  and posting only, click Submit at most once.
- It stops, and the job goes to `data/company_sites.md`, at any captcha or "I am not a robot"
  check (it never tries to solve one), a code or link sent to your email or phone, two-factor,
  payment, or an identity number you have not given.
- For the career-site password it types the word `COMPANY_SITE_PASSWORD`; the Playwright server
  swaps in the real one from `.env` and blanks it out of everything the model reads back, so the
  password never reaches the model.
- It answers with a JSON report. "Submitted" counts as applied only when the confirmation it
  quotes is on the page when the bot reads it afterwards; otherwise the job is recorded as "Submit
  was clicked ..." and never tried again automatically, so nothing is sent twice.
- Each task gets a folder `reports/<date>/agent/<time> <Company - Role>/` with the task it was given
  (`task.md`), every step it took (`steps.txt`, `transcript.jsonl`), page snapshots and `report.json`; the day's report
  lists them. Long answers it wrote go to the job's `answers.md`, accounts it made to
  `data/accounts.md`.

It is used at most `BROWSER_AGENT_LIMIT` times a run, for up to `BROWSER_AGENT_TIMEOUT_S` seconds
and `BROWSER_AGENT_BUDGET_USD` each, and never on a page that stopped at a captcha, an emailed
code, or after a Submit click. Give it one page by hand, or any specific task:

```bash
python3 -m sites_bot.browser_agent --url "<company_sites.md Site link>" --title "AI Engineer" --company "Acme" --dry-run
python3 -m sites_bot.browser_agent --url "https://careers.acme.com" --task "find the AI Engineer opening in Bengaluru and tell me its closing date"
```

A task needs Node (for `npx @playwright/mcp`) and the `claude` command on `PATH`.

### Other job boards: Hirist, Instahyre

```bash
python3 -m sites_bot.platforms --dry-run          # boards in PLATFORMS: collect, rank, open each job, click nothing
python3 -m sites_bot.platforms --site hirist --limit 10
```

One loop serves every board, with the same facts, answers, ranking (`MIN_SCORE`, `MAX_DAYS_OLD`)
and records as Naukri. It reads the board's own job feed for your profile, then one search page per
keyword, ranks the cards, opens each chosen job and clicks Apply. A one-click apply, or the board's
own question form (answered from `data/` like a company site), counts as applied only when the job
page shows **Applied** after a reload; such applications use no Naukri quota and are marked with the
board's name in the daily report. A board that sends the job to the employer's site hands it to the
company-site flow (`EXTERNAL_APPLY`); a form the script cannot finish goes to the browser agent when
`BROWSER_AGENT=true`, otherwise to `data/company_sites.md`. A job where Apply was clicked but the
board never showed Applied is never clicked again automatically.

Sign in to each board once in the bot's browser (the run stops with this hint when a board is
signed out), and finish the board's own profile, since recruiters there read it:

```bash
scripts/google_login.sh https://www.hirist.tech/ https://www.instahyre.com/login/
python3 -m sites_bot.browser_agent --url "https://www.instahyre.com/candidate/onboard/" \
  --task "Complete her candidate profile on this job site from the facts; upload the resume; never invent anything"
```

Each board is one `Board` record at the top of `sites_bot/platforms.py`: its feed and search
addresses, the pattern of its job links, and the words on its Apply and Applied buttons.

### Cold emails to recruiters (drafts only)

```bash
python3 -m sites_bot.cold_email --dry-run         # print what it would write
python3 -m sites_bot.cold_email --scan-naukri     # also read recent well-scored Naukri job pages
python3 -m sites_bot.cold_email --to hr@acme.in --company "Acme" --title "AI Engineer" --url "<posting>"
```

- **Who gets one:** only an address a company published for applications: a posting's text ("share
  your CV at hr@..."), a career page the bot or the browser agent read, a Naukri job page. Support,
  no-reply and privacy mailboxes, and addresses with no hiring words around them, are left out.
  Nothing is guessed or looked up elsewhere.
- **What it says:** written from your resume and that posting by the local `claude`, 70 to 190
  words, first person, checked like the tailored summary (no tool, employer or number your resume
  does not name, no filler words, no em dashes), then signed with your name, phone, LinkedIn and
  portfolio. The resume tailored for that job is attached, or the base one.
- **Never sent:** each email is saved as `reports/<date>/emails/<Company - Role> (<address>).eml`;
  double-click to open it in Mail as a draft, check it, send. With `GMAIL_APP_PASSWORD` set for
  `COLD_EMAIL_FROM` (default `GOOGLE_EMAIL`), it is also put in that Gmail account's **Drafts**.
- **Once per address:** `data/cold_emails.jsonl` records every draft; the same address is not written
  to again for 30 days. At most `COLD_EMAIL_LIMIT` drafts a run. The day's report lists them.

### Daily report

Every Naukri run, profile update and LinkedIn post rewrites `reports/<YYYY-MM-DD>/report.md`:

- jobs applied to today, on Naukri and on company sites, with links;
- jobs tried but not applied, with the reason (company site needs you, unanswered question, error);
- each run's numbers;
- **left for you**: company-site applications to finish, questions waiting in `answers.txt`,
  blank facts in `profile.yaml`;
- the three profile-refresh slots, the resume on the profile, resumes tailored today;
- LinkedIn: the post made today, or the draft waiting for you;
- where `answers.txt` and `profile.yaml` disagree, and what the AI filled in today, with its quotes;
- **logs**: every run also saves its full log to `reports/<YYYY-MM-DD>/logs/<tool>-<HHMMSS>.log`
  (naukri, company-site, resume, assist, profile-update, linkedin), linked from the report;
- **learning**: today's module from the PrepForge course in `course/` (`COURSE_DIR`), following its
  8-week plan (DSA, then system design, full stack, ML/GenAI, behavioral), one module a day from
  `COURSE_START_DATE` or from the first report.

```bash
python3 -m common.report --print          # rebuild today's report and show it
python3 -m common.report --date 2026-10-09
python3 course/serve.py                       # the course site at http://localhost:8000
```

Everything in the report comes from the records: the database, `data/`, `logs/`, `linkedin/`.
The report itself is not written by a model; the AI's file edits it lists carry their quotes.

## 💼 LinkedIn: one post a day

`linkedin_bot` finds a fresh article on your topics, writes a short reaction in
your own words, draws a plain 1200x627 image card, and publishes the two through
a logged-in Chrome session. One post a day, never two.

```bash
python3 -m linkedin_bot --dry-run      # article + post + card printed, no browser
python3 -m linkedin_bot --propose      # also saves linkedin/drafts/<date>.md and sends it on Telegram
python3 -m linkedin_bot --post         # publish today's draft (or a given file: --post path.md)
python3 -m linkedin_bot --if-due       # what the launchd agent runs
```

How the writing stays yours:

- The model gets a fixed list of facts about you (the `VOICE` block at the top of
  `linkedin_bot/writer.py`) and may not claim anything else. Edit that block when
  your work changes.
- Every draft is linted before it is accepted: no emojis, no em dashes, no
  exclamation marks, no bullet lists, no "excited to share", "game-changer",
  "delve", "leverage" and the rest of the usual vocabulary, no rhetorical
  "it's not X, it's Y", no restating the headline, 450 to 1300 characters, the
  article URL alone on the last line. Findings go back to the model, three
  tries, then it gives up for the day rather than post something weak.
- The card carries one sentence of yours, your name, your site and the source.
  No stock art.

First login: run `python3 -m linkedin_bot --post` once with `LINKEDIN_EMAIL` and
`LINKEDIN_PASSWORD` in `.env`. LinkedIn usually asks for a verification code
the first time; finish it in the Chrome window (the bot waits up to five
minutes). The session is kept in `.browser-profile-linkedin/`, separate from
the Naukri profile, so later runs do not ask again. Headless runs cannot answer
a check and exit 2.

Publishing is verified at every step. The typed text is read back from the
editor and must match the draft before the image is attached; the image must
show in the composer before Post is clicked; Post is clicked once, then the bot
waits for LinkedIn's "Post successful" toast or for the post at the top of the
feed. If neither appears it reports "unconfirmed", marks the day done so it
cannot post twice, and sends a Telegram alert; check your profile by hand.

Run it on a schedule:

```bash
./scripts/install_linkedin_poster.sh   # launchd agent, every 30 min, acts once a day after LINKEDIN_POST_TIME
./scripts/linkedin_status.sh           # agent state, today's entry, last log lines
```

Start with `LINKEDIN_AUTO_POST=false`: for a few days the daily run only saves
`linkedin/drafts/<date>.md` with its card next to it and sends the text on
Telegram. Read them. When you are happy with the voice, set
`LINKEDIN_AUTO_POST=true` and it posts on its own. A draft you edited by hand
goes out with `python3 -m linkedin_bot --post linkedin/drafts/<date>.md`.

Files: drafts and cards in `linkedin/drafts/`, the posted-URL list and per-day
record in `linkedin/state.json`, logs in `logs/linkedin.log`, failure
screenshots in `screenshots/linkedin-*.png`. All gitignored. The same
Desktop/Documents/Downloads warning as the profile updater applies to launchd.

Two honest notes. LinkedIn's User Agreement forbids automated access, and an
account that posts through a bot can be restricted; the compliant route is a
LinkedIn developer app with the "Share on LinkedIn" product, which this project
does not implement. And LinkedIn changes its markup often: every selector the
publisher uses lives in the tuples at the top of `linkedin_bot/publisher.py`,
in the order they are tried, so a breakage is a one-tuple fix.

## 🔧 2026 Naukri.com Update

The bot has been updated to work with Naukri.com's 2026 redesign. Key changes:

| Old (original script) | New (updated) |
|----------------------|---------------|
| Job cards: `article.jobTuple.bgWhite.br4.mb-8` | Job cards: `div.srp-jobtuple-wrapper > div.cust-job-tuple` |
| Title links: `a.title.fw500.ellipsis` | Title links: `a.title` (inside `h2`) |
| Search URL: `/{keyword}-{page}` | Search URL: `/{keyword}-jobs` or `/{keyword}-jobs-in-{location}` |
| Apply button: `//*[text()='Apply']` | Apply button: `//button[contains(text(),'Apply on company site')]` |
| Page structure: `article` tags | Page structure: React/Next.js app using `div` with hashed CSS classes |

## 📁 Project Structure

```
Naukri-autoapply-bot/
├── .env.example          # Example environment configuration (copy to .env)
├── .gitignore            # Files to exclude from git
├── requirements.txt      # Python dependencies
├── README.md             # This file
├── profile.example.yaml  # (in naukri_bot/) copy to data/profile.yaml and fill in your facts
│
├── sandy/                # the terminal screen that runs everything (../sandy)
├── course/               # the PrepForge study site Sandy reads (python3 course/serve.py)
├── naukri_bot/           # v2 package — the maintained bot (python3 -m naukri_bot)
│   ├── __main__.py       #   entry point
│   ├── cli.py            #   argument parsing + pipeline wiring
│   ├── models.py         #   shared dataclasses; every other module imports from here
│   ├── config.py         #   .env -> Settings
│   ├── profile.py        #   profile.yaml + resume -> Profile
│   ├── browser.py        #   driver factory with anti-detection
│   ├── auth.py           #   login that VERIFIES it worked
│   ├── sources.py        #   candidate collection (freshness-sorted search + recommended)
│   ├── ranking.py        #   resume-based scoring — our order, not Naukri's
│   ├── llm.py            #   LLM client (claude CLI by default, no API key needed)
│   ├── answers.py        #   screening answers: exact cache -> profile -> LLM -> abstain
│   ├── apply.py          #   verified apply; native vs external redirect
│   ├── external.py       #   apply on company websites (python3 -m sites_bot.external)
│   ├── accounts.py       #   career-site sign-in / sign-up (Google, then email + password)
│   ├── page_brain.py     #   no form on a company page: removed posting, or ask the model what to click
│   ├── browser_agent.py  #   stuck company site: Claude Code drives this Chrome via Playwright MCP
│   ├── platforms.py      #   other job boards: Hirist, Instahyre (python3 -m sites_bot.platforms)
│   ├── cold_email.py     #   recruiter emails as drafts, never sent (python3 -m sites_bot.cold_email)
│   ├── assist.py         #   AI fills answers.txt / profile.yaml blanks from quoted lines (python3 -m common.assist)
│   ├── chatbot.py        #   questionnaire drawer handling
│   ├── early_access.py   #   share interest on Early Access roles (no apply quota)
│   ├── ledger.py         #   SQLite applied-history + rolling 24h quota ledger
│   ├── resume.py         #   LaTeX resume -> PDF, per-job tailoring, upload (python3 -m common.resume)
│   ├── report.py         #   reports/<date>/report.md (python3 -m common.report)
│   └── update_profile.py #   keep the profile "recently updated" (python3 -m naukri_bot.update_profile)
│
├── linkedin_bot/         # one LinkedIn post a day (python3 -m linkedin_bot)
│   ├── config.py         #   LINKEDIN_* keys from the same .env
│   ├── news.py           #   RSS / Atom / Hacker News, scored by your topics
│   ├── writer.py         #   your VOICE facts + the slop lint; edit VOICE when your work changes
│   ├── card.py           #   1200x627 image card
│   ├── publisher.py      #   Selenium publish, verified at every stage; selectors at the top
│   └── cli.py            #   --dry-run / --propose / --post / --if-due
│
├── data/                 # YOUR files: profile.yaml (facts), answers.txt (answers), company_sites.md (to finish),
│                         #   accounts.md (career-site accounts), backups/ (before each AI edit)
├── resume/               # base.tex (your resume) + out/base and out/tailored/<Company - Role>/
├── reports/              # one folder per day: report.md + logs/ of every run; ai_changes.jsonl (auto-generated)
├── scripts/              # launchd install/run/status, google_login.sh
├── linkedin/             # drafts, cards and posted-URL state (auto-generated)
├── logs/                 # profile updater + LinkedIn logs and slot memory (auto-generated)
├── screenshots/          # page captures of failed runs (auto-generated)
├── naukri_bot.db         # v2 state: applied history + quota memory (auto-generated)
├── Naukri-Edge.py        # Legacy bot script for Microsoft Edge browser
├── Naukri-Recommended.py # Legacy bot for the recommended-jobs feed
├── Naukri autoapply jobs.ipynb  # Jupyter Notebook version (legacy)
└── naukriapplied.csv     # Legacy output: applied/failed job links (auto-generated)
```

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| Browser driver not found | `webdriver-manager` handles this automatically. Ensure you're connected to the internet on first run. |
| Login failed | Double-check your `NAUKRI_EMAIL` and `NAUKRI_PASSWORD` in `.env` |
| No jobs found | Try broader keywords or remove the location filter |
| "Daily quota expired" | Naukri limits daily applications. Try again the next day. |
| "There was an error while processing your request" after Apply | Naukri's other way of saying the day is over (it began at 46 applications in 24 hours). The run stops after two in a row and those jobs are tried again next run. |
| Script too fast/slow | Adjust the `time.sleep()` values in the script if needed |
| "Apply on company site" opens external site | This is expected — many Naukri jobs now redirect to company career pages |

## ⚠️ Disclaimer

- Use this bot responsibly and in accordance with Naukri.com's Terms of Service
- The bot mimics human behavior but excessive automation may lead to account restrictions
- This project is for educational purposes

## 🔗 Original Repository

[github.com/lordzohar/Naukri-autoapply-bot](https://github.com/lordzohar/Naukri-autoapply-bot)