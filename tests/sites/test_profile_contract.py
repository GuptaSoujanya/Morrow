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
