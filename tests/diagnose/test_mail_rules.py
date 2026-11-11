import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from diagnose import mail_rules


def test_platform_from_sender_domain():
    assert mail_rules.platform_of("Naukri <noreply@naukri.com>") == "naukri"
    assert mail_rules.platform_of("jobs@mail.hirist.tech") == "hirist"
    assert mail_rules.platform_of("no-reply@us.greenhouse-mail.io") == "ats"
    assert mail_rules.platform_of("priya@acme.in") == "employer"
    assert mail_rules.platform_of("someone@gmail.com") == "personal"


def test_interview_beats_platform_noise():
    verdict = mail_rules.classify("Priya <priya@acme.in>", "Interview invitation: Software Engineer at Acme")
    assert verdict.kind == "INTERVIEW" and verdict.positive


def test_interview_tips_newsletter_is_promo_not_interview():
    verdict = mail_rules.classify("Naukri <noreply@naukri.com>", "5 interview tips to crack your next round")
    assert verdict.kind in ("PROMO", "JOB_ALERT")
    assert not verdict.positive


def test_shortlist_and_profile_view_are_distinct():
    assert mail_rules.classify("hr@startup.io", "You have been shortlisted for the next round").kind == "SHORTLIST"
    assert mail_rules.classify("noreply@naukri.com", "A recruiter viewed your profile").kind == "PROFILE_VIEW"


def test_rejection_and_acknowledgement():
    assert mail_rules.classify("careers@big.com", "Update on your application: we will not be moving forward").kind == "REJECTION"
    assert mail_rules.classify("no-reply@wellfound.com", "Your application to Acme has been sent").kind == "ACKNOWLEDGEMENT"


def test_scheduler_domain_is_interview():
    assert mail_rules.classify("notifications@calendly.com", "Confirmed: 30 Minute Meeting").kind == "INTERVIEW"


def test_job_alert_is_noise():
    verdict = mail_rules.classify("alerts@instahyre.com", "12 new jobs matching Software Engineer in Remote")
    assert verdict.kind == "JOB_ALERT" and mail_rules.is_noise(verdict)


def test_unknown_hiring_mail_stays_other_for_the_model():
    verdict = mail_rules.classify("rahul@someco.com", "About your profile")
    assert verdict.kind == "OTHER" and verdict.hiring_related


def test_linkedin_hiring_alerts_are_alerts_not_outreach():
    verdict = mail_rules.classify("LinkedIn <jobs-noreply@linkedin.com>", "Citi is hiring for a LLM role")
    assert verdict.kind == "JOB_ALERT"


def test_reply_to_cold_mail_is_positive():
    verdict = mail_rules.classify("Titiksha Singh <titiksha@incubyte.co>", "RE: Software Craftsperson/Typescript- II at Incubyte")
    assert verdict.kind == "REPLY" and verdict.positive


def test_interview_marketing_and_google_notices_are_not_interviews():
    assert mail_rules.classify("Naukri <info@naukri.com>", "Be interview-ready by learning from previous applicants").kind != "INTERVIEW"
    assert mail_rules.classify("Wellfound <team@wellfound.com>", "Ready to ace your interview? We're here to help.").kind != "INTERVIEW"
    assert not mail_rules.classify("Google <no-reply@accounts.google.com>", "You shared some Google Account data with interview-7d0b2.firebaseapp.com").positive
    assert mail_rules.classify("The Goodfit Team <invitations@goodfit.io>", "Goodfit Interview - Login Link").kind == "INTERVIEW"
    assert mail_rules.classify("naukri <naukri@naukri.com>", "You are Shortlisted-Follow the steps to move forward.").kind == "SHORTLIST"


def test_board_notification_with_re_prefix_is_not_a_reply():
    verdict = mail_rules.classify("hirist.tech <noreply@hirist.tech>", "Re: AI Engineer - Enterprise Conversational Platform")
    assert verdict.kind != "REPLY"
