from concurrent.futures import ThreadPoolExecutor

import pytest

from common.models import Profile
from common.profile_plan import ProfilePlan
from common import profile_record
from sites_bot import profile_agent as agent, profile_contract as contract


@pytest.mark.parametrize('section', [
    agent.Section('Skills', 'already_ok', after='Python', on_page=False),
    agent.Section('Skills', 'updated', after='Python', on_page=None),
    agent.Section('Skills', 'updated', after='Python, SQL', on_page=True, missing=['SQL']),
    agent.Section('Projects', 'needs_input', note='start date missing'),
    agent.Section('Projects', 'needs_review', note='two matching entries'),
    agent.Section('Skills', 'skipped'),
])
def test_unresolved_fields_cannot_claim_completion(section):
    result = agent.ProfileCheck(False, '', sections=[section])
    assert not agent._verdict(result)[0]
    assert not result.coverage['complete']
    assert result.coverage['percent'] < 100


def test_unreadable_and_empty_reports_never_pass():
    for result in [agent.ProfileCheck(False, ''), agent.ProfileCheck(False, '', page_read=False)]:
        assert not agent._verdict(result)[0]
        assert result.coverage['percent'] == 0


def test_short_evidence_cannot_prove_a_full_skill_list():
    section = agent.Section('Skills', 'updated', after='Python, SQL, AWS, Java', evidence='Python')
    assert agent.confirm(section, 'Skills Python') == (False, ['SQL', 'AWS', 'Java'])
    section.target = 'Python, SQL, AWS, Java, Go'
    section.after = 'Python'
    assert agent.confirm(section, 'Skills Python')[0] is False


def test_an_already_ok_report_must_still_satisfy_the_approved_target():
    result = agent.ProfileCheck(False, '', sections=[agent.Section('Skills', 'already_ok', after='Python')])
    agent.add_planned(result, [dict(name='Skills', action='keep', target='Python, SQL')], 'Skills Python')
    assert result.sections[0].wanted == 'Python, SQL'
    assert agent.confirm(result.sections[0], 'Skills Python') == (False, ['SQL'])


def test_omitted_keep_fields_remain_in_the_denominator():
    result = agent.ProfileCheck(False, '', sections=[agent.Section('About', 'updated', after='Text', on_page=True)])
    agent.add_planned(result, [dict(name='Education', action='keep', current='B.Tech')], 'About Text')
    assert result.coverage['total'] == 2
    assert result.coverage['percent'] == 50
    assert not agent._verdict(result)[0]


@pytest.mark.parametrize('field,target,page,expected', [
    ('current_ctc_lpa', '16 LPA', 'Current salary ₹1,60,000', False),
    ('current_ctc_lpa', '16 LPA', 'Current salary ₹16,00,000', True),
    ('current_ctc_lpa', '16 LPA', 'Current CTC 16 LPA', True),
    ('current_ctc_lpa', '16 LPA', 'Current salary 1.6 lakh Expected salary 16 LPA', False),
    ('current_ctc_lpa', '16 LPA', 'Expected salary 16 LPA', None),
    ('notice_period_days', '15 days', 'Current CTC 16 LPA Notice period 15 days', True),
    ('notice_period_days', '15 days', 'Notice period 30 days Expected salary 15 LPA', False),
    ('total_experience_years', '2.9 years', 'Total experience 2.5 years', False),
    ('total_experience_years', '2.9 years', 'Total experience 2 years 11 months', True),
    ('current_location', 'Indore, India', 'Current location Gurugram Preferred location Indore', False),
    ('current_location', 'Indore, India', 'Current location Indore, Madhya Pradesh, India', True),
    ('current_location', 'Indore, India', 'Currently located in Indore Only willing to work in Pune', True),
    ('current_location', 'Gurugram, India', 'Current location Gurgaon, Haryana, India', True),
    ('current_location', 'Gurugram, India', 'Current location Indore Preferred location Gurgaon', False),
    ('notice_period_days', '15 days', 'Can start working 15 days after accepting offer', True),
    ('total_experience_years', '2.9 years', 'Total professional experience of 3 years', False),
    ('total_experience_years', '2.9 years', 'experienceOneTheme 2 Years 9 Months walletOneTheme ₹ 16,00,000', False),
    ('total_experience_years', '2.9 years', 'experienceOneTheme 2 Years 11 Months walletOneTheme ₹ 16,00,000', True),
    ('current_ctc_lpa', '16 LPA', 'experienceOneTheme 2 Years 9 Months walletOneTheme ₹ 16,00,000 phoneOneTheme', True),
    ('current_location', 'Gurugram, India', 'locationOt Gurugram, INDIA experienceOneTheme 2 Years 9 Months', True),
    ('current_location', 'Gurugram, India', 'Headline Gurugram, Haryana, India · https://www.linkedin.com/in/me/overlay/contact-info/ Contact info', True),
    ('current_location', 'Gurugram, India', 'Indore, Madhya Pradesh, India · https://www.linkedin.com/in/me/overlay/contact-info/ About: seeking work in Gurugram, Haryana, India', None),
])
def test_facts_are_checked_with_their_own_labels_and_units(field, target, page, expected):
    assert contract.verify_fact(field, target, page)[0] is expected


def test_facts_override_a_wrong_keep_plan_and_omitted_projects_are_restored():
    profile = Profile(current_ctc_lpa=16, current_location='Indore, India', total_experience_years=2.9)
    edits = [dict(name='Current salary', target='1.6 LPA', action='keep', current='1.6 LPA')]
    plan = ProfilePlan(projects=[dict(name='Morrow', description='A project description')])
    result = contract.reconcile(edits, profile, 'naukri', plan)
    salary = next(e for e in result if e['name'] == 'Current salary')
    assert salary['target'] == '16 LPA' and salary['action'] == 'update'
    assert any(e['name'] == 'Project: Morrow' for e in result)
    assert any(e['name'] == 'Notice period' and e['action'] == 'skip' for e in result)


def test_invalid_numeric_facts_are_rejected_before_browser_edits():
    with pytest.raises(ValueError, match='finite'):
        contract.fact_edits(Profile(current_ctc_lpa=float('nan')), 'naukri')


def test_decimal_experience_has_unambiguous_month_selectors():
    edits = contract.fact_edits(Profile(total_experience_years=2.9), 'naukri')
    experience = next(edit for edit in edits if edit['fact_key'] == 'total_experience_years')
    assert experience['target'] == '2.9 years'
    assert '2 years and 11 months' in experience['why']


def test_matching_project_description_cannot_omit_supplied_dates():
    profile = Profile(extra_facts={'projects_detail': [
        dict(name='Morrow', start='2026-08', end='2026-10', status='Completed')]})
    edits = contract.reconcile([dict(name='Project: Morrow', action='keep', current='Existing description', target='')],
                               profile, 'linkedin', None)
    dates = next(edit for edit in edits if edit['name'] == 'Project dates: Morrow')
    assert dates['target'] == 'Aug 2026 - Oct 2026'
    assert dates['project_dates'] == dict(name='Morrow', start='2026-08', end='2026-10')
    result = agent.ProfileCheck(False, '')
    agent.add_planned(result, [dates], '')
    assert result.sections[0].project_dates == dates['project_dates']
    assert not result.coverage['complete']


@pytest.mark.parametrize('body,expected', [
    ('Morrow Aug 2026 - Oct 2026 A description', True),
    ('Morrow August 2026 – October 2026 A description', True),
    ('Morrow Aug 2026 - Present A description', False),
    ('Morrow Sep 2026 - Oct 2026 A description', False),
    ('Morrow Description says Aug 2026 - Oct 2026', False),
    ('Another project Aug 2026 - Oct 2026', None),
    ('Morrow Description https://www.linkedin.com/in/me/details/projects/edit/forms/2/ Another project Aug 2026 - Oct 2026', False),
])
def test_project_dates_require_the_correct_entry_and_date_fields(body, expected):
    dates = dict(name='Morrow', start='2026-08', end='2026-10')
    section = agent.Section('Project dates: Morrow', 'updated', project_dates=dates,
                            target='Aug 2026 - Oct 2026')
    page = 'https://www.linkedin.com/in/me/details/projects/edit/forms/1/ ' + body
    assert agent.confirm(section, page)[0] is expected


def test_invalid_project_timeline_is_never_sent_to_an_editor():
    profile = Profile(extra_facts={'projects_detail': [dict(name='RideMate', start='2025-11', end='2024-09')]})
    edit = contract.project_date_edits(profile, 'linkedin')[0]
    assert edit['action'] == 'skip' and edit['target'] == ''
    assert 'needs review' in edit['why']


def test_optional_missing_project_dates_do_not_get_invented():
    profile = Profile(extra_facts={'projects_detail': [dict(name='Morrow', start='2026-08')]})
    assert contract.project_date_edits(profile, 'linkedin') == []
    assert contract.project_date_edits(profile, 'instahyre') == []


def test_naukri_project_dates_are_scoped_to_the_card_header():
    dates = dict(name='RideMate', start='2024-09', end='2024-09')
    page = 'RideMate editOneTheme Self (Offsite) Sep 2024 to Sep 2024 ( Full Time ) A description'
    assert contract.verify_project_dates(dates, page)[0] is True
    page = 'RideMate editOneTheme Self (Offsite) A description. Another project editOneTheme Self (Offsite) Sep 2024 to Sep 2024'
    assert contract.verify_project_dates(dates, page)[0] is False


def test_duplicate_detection_uses_distinct_entry_ids_not_repeated_views():
    first = dict(kind='projects', id='123', name='RideMate')
    assert contract.duplicates([first, first]) == []
    assert len(contract.duplicates([first, dict(first, id='456')])) == 1
    assert contract.duplicates([first, dict(first, name='Different project', id='456')]) == []


def test_duplicate_warning_blocks_even_with_every_value_present():
    result = agent.ProfileCheck(False, '', sections=[agent.Section('About', 'already_ok', after='Text', on_page=True)],
                                issues=['Duplicate projects: ridemate'])
    assert not agent._verdict(result)[0]
    assert result.coverage['percent'] == 99
    assert not result.coverage['complete']


def test_retries_have_stable_operation_ids_but_new_targets_do_not():
    edit = dict(name='Project: Morrow', target='Description')
    assert contract.operation_id('linkedin', edit) == contract.operation_id('linkedin', dict(edit))
    assert contract.operation_id('linkedin', edit) != contract.operation_id('linkedin', dict(edit, target='Changed'))


def test_a_duplicate_audit_with_no_duplicates_is_not_a_warning():
    assert contract.report_issues({'sections': [dict(name='Projects', note='No duplicate entries found.')]}) == []
    assert contract.report_issues({'sections': [dict(name='Projects', note='Morrow (two entries)')]})


def test_a_company_alias_does_not_create_an_extra_employment_task():
    plan = ProfilePlan(experience=[dict(company='Example Co (formerly Old Co)', description='Description')])
    edits = [dict(name='Employment: Example Co', target='Description', action='keep', current='Description')]
    result = contract.reconcile(edits, None, 'linkedin', plan)
    assert [e['name'] for e in result] == ['Employment: Example Co']


def test_atomic_field_aliases_share_one_target_but_job_locations_do_not():
    assert agent._same_section('Total experience', 'Total Work Experience')
    assert agent._same_section('Current salary', 'Basic info: Current CTC')
    assert not agent._same_section('Current location', 'Employment: Example Co - current location')
    profile = Profile(current_ctc_lpa=16)
    edits = [dict(name='Basic info: Current CTC', target='1.6 LPA', action='keep', current='1.6 LPA')]
    result = contract.reconcile(edits, profile, 'naukri', None)
    assert len([e for e in result if e.get('fact_key') == 'current_ctc_lpa']) == 1


def test_one_target_cannot_overwrite_two_ambiguous_entries():
    result = agent.ProfileCheck(False, '', sections=[
        agent.Section('Employment: Example Co - role one', 'already_ok', after='Role one'),
        agent.Section('Employment: Example Co - role two', 'already_ok', after='Role two')])
    agent.add_planned(result, [dict(name='Employment: Example Co', action='update', target='New role')], '')
    assert result.issues == ['Ambiguous section match: Employment: Example Co']
    assert all(not s.target for s in result.sections)


def test_hirists_short_field_is_verified_against_the_approved_short_summary():
    plan = ProfilePlan(summary='Long ' * 200, short_summary='A precise short summary.')
    edits = [dict(name='About (profile summary)', action='keep', target=plan.summary, current=plan.short_summary)]
    result = contract.reconcile(edits, None, 'hirist', plan)
    assert result[0]['target'] == plan.short_summary


def test_user_school_and_photo_exclusions_preserve_college_and_projects():
    profile = Profile(extra_facts={'profile_update_preferences': {
        'skip_school_education': True, 'skip_profile_photo': True}})
    for name in ('School education', 'Education: Class XII / Class X', 'Profile Picture', 'Profile photo'):
        assert contract.exclusion_reason(profile, name)
    for name in ('Education: B.Tech', 'Education: Medi-Caps University', 'Project: Photo app', 'Current location'):
        assert not contract.exclusion_reason(profile, name)
    edits = [dict(name='Education: Class X', target='School details', action='fill')]
    scoped = contract.reconcile(edits, profile, 'naukri', None)
    assert scoped[0]['action'] == 'skip' and scoped[0]['target'] == ''


def test_skipped_school_and_photo_do_not_block_requested_scope(monkeypatch, tmp_path):
    from sites_bot.board import Board
    board = Board('naukri', 'Naukri', '', (), '', '', '', '', '', profile_url='')
    profile = Profile(extra_facts={'profile_update_preferences': {
        'skip_school_education': True, 'skip_profile_photo': True}})
    monkeypatch.setattr(agent, '_read_profile', lambda *args: 'Profile completeness 95% About Verified summary')
    monkeypatch.setattr(agent, 'screenshot', lambda *args: None)
    monkeypatch.setattr(agent, '_viewport', lambda *args: None)
    monkeypatch.setattr(agent, '_vision_check', lambda *args: {})
    report = {'sections': [dict(name='About', action='already_ok', after='Verified summary'),
                           dict(name='Education: Class XII', action='needs_input'),
                           dict(name='Profile photo', action='needs_input')]}
    edits = [dict(name='Education: Class XII', action='fill', target='School details')]
    result = agent.check(object(), board, object(), report, None, tmp_path, edits, profile=profile)
    assert result.saved and result.coverage['complete']
    assert result.coverage['verified'] == result.coverage['total'] == 1
    assert len(result.coverage['excluded']) == 2
    assert result.completeness_after == '95%'  # the website's meter remains separate
    assert result.needs_repair == []


def test_linkedin_receives_current_city_without_salary_or_experience_fields():
    edits = contract.fact_edits(Profile(current_location='Gurugram, India', current_ctc_lpa=16), 'linkedin')
    assert [(e['name'], e['target']) for e in edits] == [('Current location', 'Gurugram, India')]


def test_parallel_boards_do_not_overwrite_each_others_reports(tmp_path):
    result = agent.ProfileCheck(True, '', sections=[agent.Section('About', 'already_ok', after='Text', on_page=True)])
    records = [profile_record.digest('board%d' % i, 'Board', result) for i in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda record: profile_record.save(record, tmp_path), records))
    assert len(profile_record.load(tmp_path)) == len(records)
    assert len(profile_record.history(tmp_path)) == len(records)


def test_cutshort_keeps_company_history_without_asking_for_unavailable_role_prose():
    from cutshort_bot.board import BOARD as cutshort
    plan = ProfilePlan(experience=[dict(company='Example AI (formerly Old Co)', title='Engineer', description='Long prose')])
    edits = [dict(name='Employment: Example AI', target='Long prose', action='skip')]
    result = contract.reconcile(edits, None, 'cutshort', plan)
    assert result[0]['target'] == 'Example AI' and result[0]['action'] == 'update'
    assert not agent.unsupported_section(cutshort, 'Employment: Example AI')


def test_summary_alias_does_not_add_a_second_task_for_the_same_editor():
    plan = ProfilePlan(summary='Saved summary')
    edits = [dict(name='About / summary', target='Saved summary', action='update')]
    result = contract.reconcile(edits, None, 'cutshort', plan)
    assert len(result) == 1


def test_board_character_limits_keep_verification_target_equal_to_entered_text():
    headline = 'Software Engineer building reliable applications with Python and TypeScript. ' * 4
    plan = ProfilePlan(headline=headline, short_summary='I build reliable applications. ' * 30)
    edits = contract.reconcile([dict(name='Your bio / Headline', target=headline, action='update')],
                               None, 'wellfound', plan)
    assert len(edits[0]['target']) <= 160 and headline.startswith(edits[0]['target'])
    summary = contract.reconcile([dict(name='Profile summary (About)', target='wrong full summary', action='update')],
                                 None, 'hirist', plan)[0]['target']
    assert len(summary) <= 500 and plan.short_summary.startswith(summary)


def test_live_board_city_labels_are_verified_without_using_preferred_cities():
    assert contract.verify_fact('current_location', 'Gurugram, India',
                                'Your current city Gurugram Office preference Pune')[0] is True
    assert contract.verify_fact('current_location', 'Gurugram, India',
                                'Where are you based? Pune Preferred location Gurugram')[0] is False


def test_cutshort_current_salary_alias_keeps_units_and_separate_expected_salary():
    assert contract.verify_fact('current_ctc_lpa', '16 LPA',
                                'Your current or last drawn salary ? INR 16 Lacs per year')[0] is True
    assert contract.verify_fact('current_ctc_lpa', '16 LPA',
                                'Your current or last drawn salary ? INR 1.6 Lacs per year Expected salary 16 LPA')[0] is False


def test_cutshort_does_not_copy_total_experience_into_full_time_only_field():
    edits = contract.fact_edits(Profile(total_experience_years=2.9), 'cutshort')
    assert not any(edit.get('fact_key') == 'total_experience_years' for edit in edits)
    for field in ('full_time_experience_years', 'internship_experience_months'):
        experience = next(edit for edit in edits if edit.get('fact_key') == field)
        assert experience['action'] == 'skip' and field in experience['why']
    assert contract._summary_section('Your achievements')
    assert agent._same_section('Your achievements', 'Profile summary')
    assert contract.protected('Job-search status')
    assert contract.protected('Show current salary and minimum expected salary to employers')


def test_cutshort_supplied_experience_breakdown_is_used_and_verified_with_its_own_units():
    profile = Profile(total_experience_years=2.9, extra_facts={
        'full_time_experience_years': 2.5, 'internship_experience_months': 3})
    edits = contract.fact_edits(profile, 'cutshort')
    fulltime = next(e for e in edits if e.get('fact_key') == 'full_time_experience_years')
    internship = next(e for e in edits if e.get('fact_key') == 'internship_experience_months')
    assert fulltime['action'] == internship['action'] == 'update'
    assert fulltime['target'] == '2.5 years' and internship['target'] == '3 months'
    page = 'Full time experience only, excluding internships 2.5 years Internship experience 3 months'
    assert contract.verify_fact('full_time_experience_years', '2.5 years', page) == (True, [])
    assert contract.verify_fact('internship_experience_months', '3 months', page) == (True, [])
    assert contract.verify_fact('internship_experience_months', '3 months', page.replace('3 months', '3 years'))[0] is False
    assert contract.verify_fact('full_time_experience_years', '2.9 years', page)[0] is False


@pytest.mark.parametrize('target', ['Not provided', 'Unknown', '-3 years'])
def test_malformed_numeric_report_targets_are_unverified_instead_of_crashing(target):
    assert contract.verify_fact('full_time_experience_years', target,
                                'Full time experience only, excluding internships 3 years') == (None, [])


def test_long_single_word_still_respects_board_character_limit():
    assert len(contract._fit_text('X' * 200, 160)) == 160


@pytest.mark.parametrize('reported', [[], [agent.Section('Notice period', 'already_ok', after='15 days', on_page=True)]])
def test_skip_for_missing_facts_cannot_be_promoted_by_a_matching_page_value(reported):
    result = agent.ProfileCheck(False, '', sections=reported)
    edits = [dict(name='Notice period', action='skip', target='15 days', fact_key='notice_period_days',
                  why='needs review: conflicting saved facts')]
    agent.add_planned(result, edits, 'Notice period 15 days')
    assert result.sections[0].action == 'needs_review'
    assert result.sections[0].on_page is None
    assert not result.coverage['complete']


def test_a_protected_field_that_differs_from_the_facts_is_the_users_call_not_a_conflict():
    notes = ("Entry counts are the same before and after. The mobile number on Naukri (9993350887) "
             "differs from the facts and needs the candidate's attention.")
    assert contract.report_issues({'notes': notes}) == []
    assert contract.report_issues({'notes': 'The current salary on Naukri differs from the facts.'}) == [
        'Factual conflict reported; compare the live profile with profile.yaml']


def test_naukris_unlabelled_profile_card_confirms_location_experience_and_salary():
    """Naukri's card puts the city, experience and salary side by side with no label on any, and its
    expected salary sits under "Preferred annual salary"; the labelled check left all four unconfirmed."""
    page = ("Ethara AI Profile last updated - Today Gurugram, INDIA 2 Years 11 Months ₹ 16,00,000 9993350887 "
            "dev@example.com 15 Days or less notice period Career profile Preferred annual salary ₹20,00,000 Preferred shift Day")
    assert contract.verify_fact('current_location', 'Gurugram, India', page) == (True, [])
    assert contract.verify_fact('current_location', 'Pune, India', page)[0] is not True
    assert contract.verify_fact('total_experience_years', '2.9 years', page) == (True, [])
    assert contract.verify_fact('total_experience_years', '2.5 years', page)[0] is False
    assert contract.verify_fact('current_ctc_lpa', '16 LPA', page) == (True, [])
    assert contract.verify_fact('current_ctc_lpa', '18 LPA', page)[0] is False
    assert contract.verify_fact('expected_ctc_lpa', '20 LPA', page) == (True, [])
    assert contract.verify_fact('current_ctc_lpa', '16 LPA', 'Preferred annual salary ₹16,00,000') == (None, [])
