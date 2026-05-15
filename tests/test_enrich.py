import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'skills', 'get-enriched-connections', 'scripts'))
from enrich_connections import (
    handle_from_url, score_csv_row, filter_rows,
    get_location_text, get_current_title_company, get_tenure_in_role,
    build_index_entry, slim_position,
)

# --- handle_from_url ---
def test_handle_from_url_standard():
    assert handle_from_url('https://www.linkedin.com/in/rom-gilad') == 'rom-gilad'

def test_handle_from_url_trailing_slash():
    assert handle_from_url('https://www.linkedin.com/in/rom-gilad/') == 'rom-gilad'

def test_handle_from_url_with_params():
    assert handle_from_url('https://www.linkedin.com/in/rom-gilad?mini=true') == 'rom-gilad'

def test_handle_from_url_none():
    assert handle_from_url(None) is None

def test_handle_from_url_non_linkedin():
    assert handle_from_url('https://example.com') is None

# --- score_csv_row ---
def test_score_csv_row_match():
    row = {'Position': 'Senior Software Engineer', 'Company': 'Google'}
    assert score_csv_row(row, ['engineer', 'developer']) > 0

def test_score_csv_row_no_match():
    row = {'Position': 'Primary School Teacher', 'Company': 'Springfield Elementary'}
    assert score_csv_row(row, ['engineer', 'developer', 'software']) == 0

def test_score_csv_row_empty_position():
    row = {'Position': '', 'Company': ''}
    # empty title → always keep (returns 1)
    assert score_csv_row(row, ['engineer']) == 1

def test_score_csv_row_case_insensitive():
    row = {'Position': 'ENGINEER', 'Company': ''}
    assert score_csv_row(row, ['engineer']) > 0

# --- filter_rows ---
def test_filter_rows_keeps_matches():
    rows = [
        {'Position': 'Software Engineer', 'Company': 'Acme'},
        {'Position': 'Dentist', 'Company': 'Clinic'},
        {'Position': '', 'Company': ''},  # empty — always keep
    ]
    result = filter_rows(rows, ['engineer', 'developer'])
    assert len(result) == 2
    assert rows[1] not in result

def test_filter_rows_no_keywords_keeps_all():
    rows = [{'Position': 'Dentist', 'Company': 'X'}, {'Position': 'Engineer', 'Company': 'Y'}]
    assert filter_rows(rows, []) == rows

# --- get_location_text ---
def test_get_location_text_city_country():
    profile = {'location': {'parsed': {'city': 'Tel Aviv', 'country': 'Israel'}, 'linkedinText': 'Tel Aviv, Israel'}}
    assert get_location_text(profile) == 'Tel Aviv, Israel'

def test_get_location_text_empty():
    assert get_location_text({}) == ''

# --- get_current_title_company ---
def test_get_current_title_company_from_position():
    profile = {'currentPosition': [{'title': 'VP Engineering', 'companyName': 'Wix'}]}
    title, company = get_current_title_company(profile)
    assert title == 'VP Engineering'
    assert company == 'Wix'

def test_get_current_title_company_empty():
    title, company = get_current_title_company({})
    assert title == ''
    assert company == ''

# --- get_tenure_in_role ---
def test_get_tenure_in_role():
    profile = {'currentPosition': [{'duration': '3y 1m'}]}
    assert get_tenure_in_role(profile) == '3y 1m'

def test_get_tenure_in_role_empty():
    assert get_tenure_in_role({}) == ''

# --- build_index_entry ---
def test_build_index_entry_annotations_default():
    profile = {
        'firstName': 'Rom', 'lastName': 'Gilad', 'headline': 'VP Eng',
        'location': {}, 'currentPosition': [], 'experience': [],
    }
    csv_row = {'First Name': 'Rom', 'Last Name': 'Gilad', '_days_connected': 500}
    entry = build_index_entry(profile, csv_row)
    assert entry['familiarity'] == 'not_familiar'
    assert entry['recommendation'] == 'na'
    assert entry['notes'] == ''
    assert entry['outreach'] == {'reached_out': False, 'date': '', 'outcome': ''}
    assert entry['daysConnected'] == 500

# --- slim_position ---
def test_slim_position_dict():
    p = {'title': 'Engineer', 'companyName': 'Acme', 'duration': '2y'}
    assert slim_position(p) == 'Engineer at Acme (2y)'

def test_slim_position_string():
    assert slim_position('Some position') == 'Some position'

def test_slim_position_none():
    assert slim_position(None) is None
