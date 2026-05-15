import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'skills', 'rank-connections', 'scripts'))
from rank_connections import (
    parse_tenure_years, mobility_bonus, relationship_bonus,
    passes_location_filter, passes_keyword_filter, slim_position,
)

# --- parse_tenure_years ---
def test_parse_tenure_years_years_months():
    assert abs(parse_tenure_years('3y 1m') - 3.083) < 0.01

def test_parse_tenure_years_years_only():
    assert parse_tenure_years('2y') == 2.0

def test_parse_tenure_years_months_only():
    assert abs(parse_tenure_years('6 mos') - 0.5) < 0.01

def test_parse_tenure_years_long_form():
    assert abs(parse_tenure_years('2 yrs 4 mos') - 2.333) < 0.01

def test_parse_tenure_years_empty():
    assert parse_tenure_years('') is None

def test_parse_tenure_years_none():
    assert parse_tenure_years(None) is None

# --- mobility_bonus ---
def test_mobility_bonus_under_1_year():
    assert mobility_bonus('6 mos') == 0

def test_mobility_bonus_1_to_3_years():
    assert mobility_bonus('2y') == 5

def test_mobility_bonus_3_to_7_years():
    assert mobility_bonus('4y 2m') == 10

def test_mobility_bonus_over_7_years():
    assert mobility_bonus('8y') == 5

def test_mobility_bonus_unknown():
    assert mobility_bonus('') == 5   # neutral for unknown
    assert mobility_bonus(None) == 5

# --- relationship_bonus ---
def test_relationship_bonus_10_plus_years():
    assert relationship_bonus(365 * 11) == 10

def test_relationship_bonus_5_to_10_years():
    assert relationship_bonus(365 * 7) == 8

def test_relationship_bonus_3_to_5_years():
    assert relationship_bonus(365 * 4) == 5

def test_relationship_bonus_1_to_3_years():
    assert relationship_bonus(365 * 2) == 3

def test_relationship_bonus_under_1_year():
    assert relationship_bonus(180) == 1

# --- passes_location_filter ---
def test_location_filter_match():
    entry = {'location': 'Tel Aviv, Israel'}
    assert passes_location_filter(entry, 'Israel') is True

def test_location_filter_no_match():
    entry = {'location': 'New York, USA'}
    assert passes_location_filter(entry, 'Israel') is False

def test_location_filter_empty_location_keep():
    # Unknown location — always keep
    assert passes_location_filter({}, 'Israel') is True
    assert passes_location_filter({'location': ''}, 'Israel') is True

def test_location_filter_remote_keeps_all():
    entry = {'location': 'New York, USA'}
    assert passes_location_filter(entry, '') is True
    assert passes_location_filter(entry, 'remote') is True

# --- passes_keyword_filter ---
def test_keyword_filter_headline_match():
    entry = {'headline': 'Senior Software Engineer at Stripe', 'currentTitle': '', 'currentCompany': ''}
    assert passes_keyword_filter(entry, ['engineer', 'developer']) is True

def test_keyword_filter_no_match():
    entry = {'headline': 'Dentist', 'currentTitle': 'Dentist', 'currentCompany': 'Smile Clinic'}
    assert passes_keyword_filter(entry, ['engineer', 'developer', 'software']) is False

def test_keyword_filter_empty_fields_keep():
    # Unknown profession — always keep
    entry = {'headline': '', 'currentTitle': '', 'currentCompany': ''}
    assert passes_keyword_filter(entry, ['engineer']) is True

def test_keyword_filter_no_keywords_keeps_all():
    entry = {'headline': 'Dentist', 'currentTitle': '', 'currentCompany': ''}
    assert passes_keyword_filter(entry, []) is True

# --- slim_position ---
def test_slim_position_dict():
    p = {'title': 'Engineer', 'companyName': 'Acme', 'duration': '2y'}
    result = slim_position(p)
    assert 'Engineer' in result
    assert 'Acme' in result

def test_slim_position_string():
    assert slim_position('Backend Engineer at Stripe') == 'Backend Engineer at Stripe'

def test_slim_position_none():
    assert slim_position(None) is None
