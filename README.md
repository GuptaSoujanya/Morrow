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
cp naukri_bot/profile.example.yaml profile.yaml
```

Then fill in `profile.yaml`. Fields you leave blank are facts the bot **does not know** — it
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
├── profile.example.yaml  # (in naukri_bot/) copy to profile.yaml and fill in your facts
│
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
│   ├── chatbot.py        #   questionnaire drawer handling
│   └── ledger.py         #   SQLite applied-history + rolling 24h quota ledger
│
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
| Script too fast/slow | Adjust the `time.sleep()` values in the script if needed |
| "Apply on company site" opens external site | This is expected — many Naukri jobs now redirect to company career pages |

## ⚠️ Disclaimer

- Use this bot responsibly and in accordance with Naukri.com's Terms of Service
- The bot mimics human behavior but excessive automation may lead to account restrictions
- This project is for educational purposes

## 🔗 Original Repository

[github.com/lordzohar/Naukri-autoapply-bot](https://github.com/lordzohar/Naukri-autoapply-bot)