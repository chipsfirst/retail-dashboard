import json

import pandas as pd
import pytest

from scripts.build_dashboard import build_payload, render


@pytest.fixture()
def data_dir(tmp_path):
    (tmp_path / 'orders.csv').write_text(
        'invoice_no,customer_id,invoice_ts,status,country\n'
        '1001,1,2010-01-05 10:00:00,paid,United Kingdom\n'
        '1002,1,2010-02-01 10:00:00,paid,United Kingdom\n'
        'C1003,2,2010-02-01 10:00:00,cancelled,Germany\n'
        '1004,,2010-02-10 10:00:00,paid,United Kingdom\n',
        encoding='utf-8',
    )
    (tmp_path / 'order_items.csv').write_text(
        'invoice_no,stock_code,quantity,unit_price\n'
        '1001,12345,2,10.00\n'
        '1002,12346,1,5.00\n'
        'C1003,12345,-1,10.00\n'
        '1004,12345,3,10.00\n',
        encoding='utf-8',
    )
    (tmp_path / 'products.csv').write_text(
        'stock_code,description,min_price,max_price\n'
        '12345,Widget A,10.00,10.00\n'
        '12346,Widget B,5.00,5.00\n',
        encoding='utf-8',
    )
    return tmp_path


@pytest.fixture()
def payload(data_dir):
    return build_payload(str(data_dir))


def test_kpi_counts_only_paid(payload):
    kpi = payload['kpi']
    assert kpi['revenue'] == pytest.approx(2 * 10 + 1 * 5 + 3 * 10)
    assert kpi['orders'] == 3
    assert kpi['customers'] == 1
    assert kpi['repeat_share'] == pytest.approx(100.0)


def test_monthly_series(payload):
    months = {row['month']: row for row in payload['monthly']}
    assert set(months) == {'2010-01', '2010-02'}
    assert months['2010-01']['revenue'] == pytest.approx(20)
    assert months['2010-02']['revenue'] == pytest.approx(35)


def test_cancelled_country_excluded(payload):
    assert [row['country'] for row in payload['countries']] == ['United Kingdom']


def test_cohort_new_and_returning(payload):
    cohort = {row['month']: row for row in payload['cohort']}
    assert cohort['2010-01']['new'] == 1
    assert cohort['2010-02']['new'] == 0
    assert cohort['2010-02']['returning'] == 1


def test_top_products(payload):
    products = {row['description']: row['net'] for row in payload['products']}
    assert products['Widget A'] == pytest.approx(50)
    assert products['Widget B'] == pytest.approx(5)


def test_render_embeds_data(payload):
    html = render(payload)
    assert 'Online Retail II' in html
    assert '"revenue"' in html
    assert '__DATA__' not in html
    json.loads(json.dumps(payload, ensure_ascii=False))  # payload сериализуем
