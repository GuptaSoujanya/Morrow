<div align="center">

# Morrow

### Your career workspace that studies with you, tailors your resume and applies for you, all on your own computer

[![Release](https://img.shields.io/badge/Release-v1.0.0-7C5CFF?style=for-the-badge&logo=github)](https://github.com/GuptaSoujanya/Morrow/releases/tag/v1.0.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/macOS%20%7C%20Linux-111?style=for-the-badge&logo=apple)](#-quick-start)
[![Tests](https://img.shields.io/badge/Tests-1702%20passing-39D353?style=for-the-badge&logo=pytest&logoColor=white)](#-verify-it-works)
[![License](https://img.shields.io/badge/License-MIT-F5A623?style=for-the-badge)](LICENSE)

<br/>

<p align="center">
  <a href="https://github.com/GuptaSoujanya/Morrow/stargazers"><img src="https://img.shields.io/github/stars/GuptaSoujanya/Morrow?style=for-the-badge&logo=apachespark&color=FFD700&label=STARS" alt="GitHub Stars" /></a>
  &nbsp;
  <a href="https://github.com/GuptaSoujanya/Morrow/network/members"><img src="https://img.shields.io/github/forks/GuptaSoujanya/Morrow?style=for-the-badge&logo=git&color=00F2FE&label=FORKS" alt="GitHub Forks" /></a>
  &nbsp;
  <a href="https://github.com/GuptaSoujanya/Morrow/watchers"><img src="https://img.shields.io/github/watchers/GuptaSoujanya/Morrow?style=for-the-badge&logo=github&color=39D353&label=WATCHERS" alt="GitHub Watchers" /></a>
</p>

**[Quick start](#-quick-start)** · **[Screenshots](#-a-look-inside)** · **[What it does](#-what-it-does)** · **[How it works](#-how-it-works)** · **[Full guide](GUIDE.md)** · **[SoujanyaLab](https://www.soujanyalab.in/)**

<br/>

<img src=".github/assets/tour.gif" alt="A tour of the Morrow dashboard: Launchpad, Insights, Bot Crew, Applications, Learning and Action inbox" width="900"/>

<sub>A quick tour of the dashboard (example data)</sub>

</div>

<br/>

> [!NOTE]
> **The beta is free.** There's no account, subscription or payment. Your data stays on your machine; it only goes out through the browsers you sign in to and the AI CLI you already use (Claude Code or Kiro).

## ✨ Why Morrow

<table>
<tr>
<td width="33%" valign="top">

### ✅ Checked on the page
Morrow only reports a login, application, profile save or post as done after it has checked the page and seen it there.

</td>
<td width="33%" valign="top">

### 🔒 Nothing made up
Answers come only from your resume, your facts and what you've told it. When it doesn't know, it asks you in the **Action inbox** instead of guessing.

</td>
<td width="33%" valign="top">

### 🧾 Every run is recorded
Each run writes to an SQLite ledger and a daily report with links, keeps its full log, and saves the exact resume each recruiter received.

</td>
</tr>
</table>

---

## 🚀 Quick start

```bash
git clone --recurse-submodules https://github.com/GuptaSoujanya/Morrow.git
cd Morrow
bash setup.sh
```

That's it. `setup.sh` does the following, in order:

| Step | What happens |
|:---:|---|
| 1️⃣ | Installs Python 3.11+, Node.js, Poppler and Chrome if they're missing |
| 2️⃣ | Creates `venv/` and installs the locked Python and dashboard packages |
| 3️⃣ | Signs you in to **Claude Code** or **Kiro CLI** |
| 4️⃣ | Installs the `morrow` command and starts the dashboard |
| 5️⃣ | Opens **http://127.0.0.1:8100/#/onboarding**, where you upload your resume and confirm your details |

<details>
<summary><b>setup.sh flags</b></summary>

| Flag | Effect |
|---|---|
| `--provider claude\|kiro` | choose the AI CLI without being asked |
| `--skip-login` | skip the AI CLI sign-in step |
| `--no-start` | install everything, but don't start the dashboard |
| `--no-open` | start the dashboard, but don't open the browser |
| `--check` | only report what's installed and what's missing |

</details>

<details>
<summary><b>Prefer to set it up by hand?</b></summary>

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.lock
./scripts/setup_user.sh          # your private data repo -> user/, and .env
python3 -m pipeline onboard      # resume + facts -> user/inputs/
python3 -m naukri_bot --dry-run  # see what it would apply to; clicks nothing
scripts/morrow install && morrow start
```

</details>

### Day to day

| Command | Does |
|---|---|
| `morrow start` | start the dashboard on http://127.0.0.1:8100 |
| `morrow stop` | stop it |
| `morrow status` | check whether it's running |
| `morrow logs` | follow the dashboard log |
| `python3 -m pipeline` | run the whole morning: study, profiles, applications, briefings (picks up where it stopped) |

> [!TIP]
> The first real run on each site opens a visible Chrome window so you can enter the OTP. After that the session is saved under `user/browser/` and later runs sign in on their own.

---

## 📸 A look inside

> Every screenshot below comes from the real dashboard running on **example data** (Example Candidate, made-up companies).

### 🏠 Launchpad: everything at a glance

<p align="center"><img src=".github/assets/launchpad.jpg" alt="Launchpad: applications sent this period, jobs discovered, jobs above the match threshold, the bot crew and what needs your attention" width="900"/></p>

Applications sent across Naukri, job boards and company sites, the jobs found and how many scored above your match threshold, and a short list of what needs you, all for the date range you pick.

### 🤖 Bot Crew: 18 specialists, one click each

<p align="center"><img src=".github/assets/crew.jpg" alt="The eighteen Morrow specialists in three rows: apply, profile and assist" width="900"/></p>

<table>
<tr>
<td width="50%"><img src=".github/assets/bot-crew-cards.jpg" alt="Bot Crew cards for Naukri, Hirist, Instahyre, Cutshort, Wellfound and Company sites with Run now and Configure"/></td>
<td width="50%" valign="top">

**Six apply, six keep your profiles current, six help you research and study.**

- **Run now** or **Configure** on each card
- Run up to **8 agents at once**, each in its own browser
- Turn on **Run in background** to hide the Chrome windows
- Each card shows how many jobs that bot found and how many applications it sent

</td>
</tr>
</table>

### 📊 Insights: see what's working

<table>
<tr>
<td width="50%"><img src=".github/assets/insights.jpg" alt="Insights summary cards: applications sent, Naukri applications, opportunities found, needs your attention"/></td>
<td width="50%"><img src=".github/assets/insights-charts.jpg" alt="Insights charts: daily application bars by channel, the job funnel and the outcome ring"/></td>
</tr>
<tr>
<td align="center"><b>Totals for the period you choose</b></td>
<td align="center"><b>Daily activity, the job funnel and the outcome of each attempt</b></td>
</tr>
</table>

### 📋 Applications and the Action inbox

<table>
<tr>
<td width="50%"><img src=".github/assets/applications.jpg" alt="Applications ledger with role, platform, outcome, match score and time"/></td>
<td width="50%"><img src=".github/assets/action-inbox.jpg" alt="Action inbox listing employer questions waiting for an answer"/></td>
</tr>
<tr>
<td align="center"><b>Every attempt with its match score and outcome; search and filter it</b></td>
<td align="center"><b>Questions Morrow wouldn't guess at. Answer once and it reuses the answer</b></td>
</tr>
</table>

### 📚 Learning: study while you apply

<table>
<tr>
<td width="50%"><img src=".github/assets/learning.jpg" alt="Today's learning: the next step and today's progress"/></td>
<td width="50%"><img src=".github/assets/dsa.jpg" alt="DSA practice lesson: learn, worked example, practice"/></td>
</tr>
<tr>
<td align="center"><b>Today's plan, built around your target role</b></td>
<td align="center"><b>DSA lessons: learn, worked example, practice (+XP)</b></td>
</tr>
</table>

### 🔁 Flows and Connections

<table>
<tr>
<td width="50%"><img src=".github/assets/flows.jpg" alt="Flows: run the whole morning workflow and resume from saved progress"/></td>
<td width="50%"><img src=".github/assets/connections.jpg" alt="Connections: saved sign-ins for Google, Naukri and the job boards"/></td>
</tr>
<tr>
<td align="center"><b>Run the whole morning; pick up where it stopped</b></td>
<td align="center"><b>Sign in once per site; Morrow never sees your password</b></td>
</tr>
</table>

### 🪄 Onboarding: from resume to ready in three steps

<table>
<tr>
<td width="33%"><img src=".github/assets/onboarding-resume.png" alt="Onboarding step 1: upload your resume"/></td>
<td width="33%"><img src=".github/assets/onboarding-profile.png" alt="Onboarding step 2: review the details read from your resume"/></td>
<td width="33%"><img src=".github/assets/onboarding-preferences.png" alt="Onboarding step 3: choose target roles and locations"/></td>
</tr>
<tr>
<td align="center"><b>1 · Upload your resume</b></td>
<td align="center"><b>2 · Check what it found</b></td>
<td align="center"><b>3 · Pick the jobs you want</b></td>
</tr>
</table>

---

## 🧩 What it does

| | Feature | Highlights |
|---|---|---|
| 📚 | **Learn** | 90-day interview plan, daily AI-researched briefings, DSA practice with a code runner, streaks, XP and badges |
| 👤 | **Profile** | Writes one profile plan from your resume to Naukri, LinkedIn, Hirist, Instahyre, Cutshort and Wellfound, then checks each one |
| 📄 | **Resume** | Compiles your LaTeX resume and tailors it for each job by reordering what's already there, never adding to it |
| 🎯 | **Apply** | Naukri, Hirist, Instahyre, Cutshort, Wellfound and company career sites (Greenhouse, Lever, Workday and more), ranked by an LLM against your resume |
| 💬 | **Answer** | Fills in screening questions from your answers, your profile and quotes from your resume. If none of them has the answer, it asks you |
| ✉️ | **Outreach** | Writes cold-email drafts to recruiters and one LinkedIn post a day, in your voice |
| 📊 | **Report** | One daily report with what was applied, what was tried, what's left for you, and every run's log |
| 🖥️ | **Dashboard** | Every bot as a button, live logs, a live view of each bot's browser, a Stop button, the application ledger and insights |

### Supported job boards

![Naukri](https://img.shields.io/badge/Naukri-0A66C2?style=flat-square)
![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=flat-square&logo=linkedin&logoColor=white)
![Hirist](https://img.shields.io/badge/Hirist-1E88E5?style=flat-square)
![Instahyre](https://img.shields.io/badge/Instahyre-00BFA5?style=flat-square)
![Cutshort](https://img.shields.io/badge/Cutshort-FF7043?style=flat-square)
![Wellfound](https://img.shields.io/badge/Wellfound-000000?style=flat-square)
![Greenhouse](https://img.shields.io/badge/Greenhouse-24A47F?style=flat-square)
![Lever](https://img.shields.io/badge/Lever-555?style=flat-square)
![Workday](https://img.shields.io/badge/Workday-F5A623?style=flat-square)

---

## ⚙️ How it works

```mermaid
flowchart LR
    R[📄 Your resume] --> O[Onboarding<br/>profile + answers]
    O --> L[📚 Learn<br/>plan + briefings]
    O --> P[👤 Profiles<br/>write + verify]
    O --> A[🎯 Apply<br/>search · rank · tailor]
    A --> Q{Question<br/>answerable?}
    Q -- yes --> S[✅ Submit + verify]
    Q -- no --> I[📥 Action inbox<br/>for you]
    S --> D[(Ledger + daily report)]
    P --> D
    L --> D
```

Each site runs in its own process with its own Chrome profile. You can also run each one in its own Docker container and watch its screen in your browser.

---

## 🧰 Requirements

| Tool | Why |
|---|---|
| **macOS** (Linux works for the bots) | launchd schedules are macOS-only |
| **Python 3.11+**, **Node 22.19+** | the bots and the dashboard |
| **Google Chrome** | every bot drives a real browser |
| **Claude Code** or **Kiro CLI**, signed in | ranking, answers, briefings, writing (no API key needed) |
| **tectonic** *(optional)* | compiling and tailoring a LaTeX resume |
| **Docker** *(optional)* | one container per site |

`setup.sh` installs the required ones for you.

---

## ✅ Verify it works

```bash
venv/bin/python -m pytest -q tests   # ~2 minutes
python3 -m pipeline status           # today's progress (read-only)
morrow status                        # is the dashboard up?
```

<details>
<summary><b>Common problems</b></summary>

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.lock` inside the venv |
| Exit code 2, "needs a human" | run with a visible window and finish the OTP in Chrome |
| Dashboard port busy | `morrow start --port 8116`, or stop the process `morrow start` names |
| A board says "signed out" | sign in again from the dashboard's **Connections** page |
| Tailoring fails | needs a `.tex` resume and `brew install tectonic` |

More in the [full guide](GUIDE.md#troubleshooting).

</details>

---

## 📖 Learn more

| Document | What's in it |
|---|---|
| **[GUIDE.md](GUIDE.md)** | every feature, command, dashboard page and `.env` key in detail |
| [froned-dashbord/README.md](froned-dashbord/README.md) | the dashboard, plus the optional accounts mode |
| [morrow-api/README.md](morrow-api/README.md) | the account API |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to help |
| [.env.example](.env.example) | every setting and its default |

---

> [!WARNING]
> Use Morrow responsibly and within each site's terms. LinkedIn's User Agreement forbids automated access, and Naukri and the other boards may restrict accounts that automate. Start with dry runs and low limits, and read the daily report. Morrow is provided for educational use.

---

## ⭐ Star History & Community

If you find Morrow helpful for your career and job application workflow, please consider starring ⭐ the repository and forking 🍴 it to stay synchronized with new updates!

<div align="center">
  <a href="https://star-history.com/#guptasoujanya/morrow&Date">
    <img src="https://api.star-history.com/svg?repos=guptasoujanya/morrow&type=Date&theme=dark" width="750" alt="Morrow Star History Chart" />
  </a>
</div>

<br/>

<div align="center">

Built by **Soujanya Gupta** at [SoujanyaLab](https://www.soujanyalab.in/) · Released under the [MIT license](LICENSE)

</div>
