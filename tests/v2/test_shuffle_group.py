"""
v2 Shuffle 层测试
"""
from __future__ import annotations

import pytest

from scripts.v2.shuffle_group import group_by_type, merge_lab_trends


def test_group_by_type():
    extracted = [
        {'report_type': 'lab', 'report_date': '2025-01-01', 'lab_values': [{'name': 'CA199', 'value': 100}]},
        {'report_type': 'lab', 'report_date': '2025-02-01', 'lab_values': [{'name': 'CA199', 'value': 150}]},
        {'report_type': 'imaging', 'report_date': '2025-01-15'},
    ]
    groups = group_by_type(extracted)
    assert len(groups['lab']) == 2
    assert len(groups['imaging']) == 1
    assert groups['lab'][0]['report_date'] == '2025-01-01'
    assert groups['lab'][1]['report_date'] == '2025-02-01'


def test_group_by_type_sorts_ascending():
    extracted = [
        {'report_type': 'lab', 'report_date': '2025-03-01'},
        {'report_type': 'lab', 'report_date': '2025-01-01'},
        {'report_type': 'lab', 'report_date': '2025-02-01'},
    ]
    groups = group_by_type(extracted)
    assert [item['report_date'] for item in groups['lab']] == ['2025-01-01', '2025-02-01', '2025-03-01']


def test_merge_lab_trends():
    lab_group = [
        {'report_date': '2025-01-01', 'lab_values': [{'name': 'CA199', 'value': 100, 'unit': 'U/ml'}]},
        {'report_date': '2025-02-01', 'lab_values': [{'name': 'CA199', 'value': 150, 'unit': 'U/ml'}]},
    ]
    trends = merge_lab_trends(lab_group)
    assert 'CA199' in trends
    assert len(trends['CA199']['trend']) == 2
    assert trends['CA199']['unit'] == 'U/ml'
    assert trends['CA199']['trend'][0]['date'] == '2025-01-01'
    assert trends['CA199']['trend'][1]['date'] == '2025-02-01'


def test_merge_lab_trends_multiple_indicators():
    lab_group = [
        {
            'report_date': '2025-01-01',
            'lab_values': [
                {'name': 'CA199', 'value': 100, 'unit': 'U/ml'},
                {'name': 'CEA', 'value': 5, 'unit': 'ng/ml'},
            ],
        },
    ]
    trends = merge_lab_trends(lab_group)
    assert 'CA199' in trends
    assert 'CEA' in trends
    assert len(trends['CA199']['trend']) == 1
    assert len(trends['CEA']['trend']) == 1


def test_merge_lab_trends_missing_lab_values():
    trends = merge_lab_trends([])
    assert trends == {}
