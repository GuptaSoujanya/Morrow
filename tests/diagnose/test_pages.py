import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from diagnose import pages

HIRIST_APPLIED = """Applied Jobs
Filter By:
Title
Application Date
Views
Applications
Recruiter Actions
Status
Actions
Quickhyre AI - Software Development Engineer
11-11-2026
48
22
0
Applied/Sent
Follow Up
Data Scientist
09-11-2026
6378
2159
2110
Applied/Sent
PixiJS Game Developer
03-11-2026
523
114
107
Not suitable
"""

HIRIST_CHATS = """My Chats
hirist iBot
Your Personal Assistant
AM
Atul Mehrotra
Atul: Hi, You are not fulfilling the eligibility criteria. I have created a WhatsApp channel where I will post openings.
Hi Soujanya Gupta
"""

INSTAHYRE_INBOX = """Inbox
All conversations
All
Unread (1)
Starred (0)
Nov 02
Shreya Rani
GreyOrange - Software Engineer II
Shreya: Hi Soujanya, Thanks for showing interest. As part of the application process, we would like you to complete a questionnaire.
Oct 29
Ayush Srivastava
GreyOrange - SDET 2
Ayush: Hi Soujanya, Thanks for showing interest in working with GreyOrange. Please complete a questionnaire.
"""

CUTSHORT_DASHBOARD = """Actively interviewing
Conversations with companies
0
Companies interested in you
25
Applications pending
0
Applications shortlisted
1
Applications rejected
Resume
2.5 years fulltime • 3 months internship (Can join in 15 days)
"""

WELLFOUND_APPLICATIONS = """Applications
Ongoing
Archived
Formr
Software Engineer
Pending
28 MINUTES AGO
FilterPixel
Senior Software Engineer — Backend
Not Accepted
MONDAY
"""

WELLFOUND_MESSAGES = """Messages
Ongoing
Archived
LearnTube.ai (backed by Google)
Kanchan VNOV 6
Hi Soujanya Gupta! Thank you for your interest in the role of Senior Backend Engineer. As the next step, we'd like you to take on a quick assessment - here's the link.
Archive
"""


def test_hirist_applied_rows_and_facts():
    parsed = pages.hirist_applied(HIRIST_APPLIED)
    assert [a["status"] for a in parsed["applications"]] == ["Applied/Sent", "Applied/Sent", "Not suitable"]
    assert parsed["applications"][1]["applicants"] == 2159
    assert parsed["facts"]["jobs_with_zero_recruiter_actions"] == 1
    assert parsed["facts"]["viewed_or_better"] == 1


def test_hirist_chat_rejection_is_flagged():
    parsed = pages.hirist_chats(HIRIST_CHATS)
    assert len(parsed["messages"]) == 1
    assert parsed["messages"][0]["rejection"] is True
    assert parsed["messages"][0]["who"] == "Atul"


def test_instahyre_inbox_lists_questionnaire_requests():
    parsed = pages.instahyre_inbox(INSTAHYRE_INBOX)
    assert len(parsed["messages"]) == 2
    assert all(m["action"] == "questionnaire" for m in parsed["messages"])
    assert parsed["facts"]["unread"] == 1


def test_cutshort_dashboard_numbers_precede_labels():
    parsed = pages.cutshort_dashboard(CUTSHORT_DASHBOARD)
    assert parsed["status_counts"]["Applications pending"] == 25
    assert parsed["status_counts"]["Applications shortlisted"] == 0
    assert parsed["status_counts"]["Applications rejected"] == 1
    assert parsed["facts"]["experience_shown"] == "2.5 years"


def test_wellfound_applications_and_messages():
    applications = pages.wellfound_applications(WELLFOUND_APPLICATIONS)
    assert applications["status_counts"] == {"Pending": 1, "Not Accepted": 1}
    assert applications["applications"][1]["company"] == "FilterPixel"
    messages = pages.wellfound_messages(WELLFOUND_MESSAGES)
    assert messages["messages"][0]["action"] == "assessment"


CUTSHORT_CONVERSATIONS = """Interested in you

Employer actions on your 26 applications

Pending
25
Shortlisted
Closed
1
Techjays
For job Senior AI Engineer

5 hours ago

[Questionnaire]
Hardwin
Agency job
For job Gen-AI Full stack

2 days ago

[Questionnaire]
Incubyte
For job Software Craftsperson/Typescript- II

1 day ago

Could you share your notice period and current CTC?
"""


def test_cutshort_conversations_rows_become_messages():
    parsed = pages.parse("cutshort", "https://cutshort.io/profile/candidate-conversations?i=all&stage=awaiting",
                         CUTSHORT_CONVERSATIONS)
    assert [m["who"] for m in parsed["messages"]] == ["Techjays", "Hardwin", "Incubyte"]
    assert parsed["messages"][0]["about"] == "Senior AI Engineer at Techjays"
    assert parsed["messages"][0]["action"] == "questionnaire" and parsed["messages"][0]["date"] == "5 hours ago"
    assert parsed["messages"][1]["who"] == "Hardwin" and "Gen-AI Full stack" in parsed["messages"][1]["text"]
    assert parsed["messages"][2]["action"] == "reply" and parsed["messages"][2]["text"].startswith("Could you share")
    assert pages.parse("cutshort", "https://cutshort.io/profile/candidate-conversations?i=all",
                       "Messages\nNo conversations here.")["messages"] == []


def test_summarise_counts_actions_across_pages():
    merged = pages.summarise("instahyre", [
        {"parsed": pages.instahyre_inbox(INSTAHYRE_INBOX)},
        {"parsed": pages.instahyre_inbox(INSTAHYRE_INBOX)},
    ])
    assert merged["facts"]["messages_needing_action"] == 2
    assert len(merged["messages"]) == 2


NAUKRI_HOME = """Profile performance
Search appearances
252
Recruiter actions
8
Upto 3X boost
"""

NAUKRI_PROFILE = """Software Engineer
at Ethara AI
Profile last updated - Today
2 Years 11 Months
15 Days or less notice period
Resume
Soujanya_Gupta_Resume.pdf
Uploaded on Nov 04, 2026
Resume headlineeditOneTheme
Software Engineer | AI Agent Evaluation, LLM Tooling | 2.9 yrs
Key skillseditOneTheme
PythonMongoDBTypeScript
"""


def test_naukri_homepage_and_profile_facts():
    home = pages.naukri_homepage(NAUKRI_HOME)
    assert home["facts"] == {"search_appearances": 252, "recruiter_actions": 8}
    profile = pages.naukri_profile(NAUKRI_PROFILE)
    assert profile["facts"]["experience"] == "2 Years 11 Months"
    assert profile["facts"]["headline"].startswith("Software Engineer | AI Agent")
    assert profile["facts"]["resume_uploaded"] == "Nov 04, 2026"
    assert profile["facts"]["profile_updated"] == "Today"


NAUKRI_PERFORMANCE = """Profile performance
252Search appearances8Recruiter actions
Summary of last 90 days
48 Search appearances in last 
 7 Days 
8 Recruiter actions on your profile
All Actions(8)NVite sent(8)
"""

NAUKRI_HISTORY = """Job application status
607Total
applies16Application
updates
Recruiter Actions
(16)
Applies on Naukri
(351)
Applies on External Site
(256)
"""

NAUKRI_INBOX = """NVites: Your invitation to apply
All (8)
Become a Pro
AI Engineer
Noida
2 - 5 Years20 - 25 LPA
Hiring for IT Services & Consulting industry
Posted by Byte Recruit It Consulting
5 Nov
Data Entry Operator
Delhi / NCR
0 - 4 Years2 - 4 LPA
"""


def test_naukri_performance_history_and_inbox():
    performance = pages.naukri_performance(NAUKRI_PERFORMANCE)
    assert performance["facts"] == {"search_appearances": 252, "recruiter_actions": 8, "search_appearances_7_days": 48}
    assert performance["status_counts"] == {"Recruiter action: NVite sent": 8}
    history = pages.naukri_history(NAUKRI_HISTORY)
    assert history["facts"] == {"total_applies": 607, "application_updates": 16, "recruiter_actions_on_applies": 16,
                                "applies_on_naukri": 351, "applies_on_external_site": 256}
    inbox = pages.naukri_inbox(NAUKRI_INBOX)
    assert inbox["facts"]["nvites"] == 8
    assert [m["about"] for m in inbox["messages"]] == ["AI Engineer, Noida", "Data Entry Operator, Delhi / NCR"]
    assert all(m["action"] == "apply-invitation" for m in inbox["messages"])
