"""Сборка статического дашборда по данным Online Retail II.

Читает подготовленные CSV из проекта sql-retail-case (или из каталога --data),
считает агрегаты и записывает один файл index.html с графиками Plotly.

Запуск:
    python3 scripts/build_dashboard.py
    python3 scripts/build_dashboard.py --data ../sql-retail-case/data --out index.html
"""

import argparse
import json
import os
from datetime import date

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.normpath(os.path.join(HERE, '..', 'sql-retail-case', 'data'))
DEFAULT_OUT = os.path.join(HERE, 'index.html')


def load_data(data_dir):
    orders = pd.read_csv(os.path.join(data_dir, 'orders.csv'), encoding='utf-8-sig',
                         dtype={'invoice_no': str, 'customer_id': 'Int64'},
                         parse_dates=['invoice_ts'])
    items = pd.read_csv(os.path.join(data_dir, 'order_items.csv'), encoding='utf-8-sig',
                        dtype={'invoice_no': str, 'stock_code': str})
    products = pd.read_csv(os.path.join(data_dir, 'products.csv'), encoding='utf-8-sig',
                           dtype={'stock_code': str})
    return orders, items, products


def build_payload(data_dir):
    orders, items, products = load_data(data_dir)

    paid = orders[orders['status'] == 'paid'].copy()
    lines = (paid.merge(items, on='invoice_no')
             .merge(products[['stock_code', 'description']], on='stock_code', how='left'))
    lines['net'] = lines['quantity'] * lines['unit_price']

    order_revenue = lines.groupby('invoice_no')['net'].sum().rename('revenue')
    paid = paid.merge(order_revenue, on='invoice_no')
    paid['month'] = paid['invoice_ts'].dt.strftime('%Y-%m')

    monthly = (paid.groupby('month')
               .agg(orders=('invoice_no', 'size'),
                    revenue=('revenue', 'sum'),
                    aov=('revenue', 'mean'),
                    median_check=('revenue', 'median'))
               .reset_index())

    countries = (paid.groupby('country', as_index=False)
                 .agg(revenue=('revenue', 'sum'), orders=('invoice_no', 'size'))
                 .sort_values('revenue', ascending=False))
    top = countries.head(8).copy()
    other = countries.iloc[8:]
    if len(other):
        top = pd.concat([top, pd.DataFrame([{
            'country': 'Другие страны',
            'revenue': other['revenue'].sum(),
            'orders': other['orders'].sum(),
        }])], ignore_index=True)

    with_customer = paid.dropna(subset=['customer_id']).copy()
    first_order = with_customer.groupby('customer_id')['invoice_ts'].min().rename('first_ts')
    with_customer = with_customer.merge(first_order, on='customer_id')
    with_customer['is_new'] = (with_customer['invoice_ts'].dt.month
                               == with_customer['first_ts'].dt.month)
    active = (with_customer.groupby(['month', 'customer_id'])
              .agg(is_new=('is_new', 'max')).reset_index())
    cohort = active.groupby('month').agg(new=('is_new', 'sum'),
                                         customers=('customer_id', 'nunique'))
    cohort['returning'] = cohort['customers'] - cohort['new']

    product_revenue = (lines.dropna(subset=['description'])
                       .groupby('description', as_index=False)['net'].sum()
                       .sort_values('net', ascending=False).head(10))

    invoices_per_customer = with_customer.groupby('customer_id')['invoice_no'].nunique()
    kpi = {
        'revenue': float(paid['revenue'].sum()),
        'orders': int(len(paid)),
        'aov': float(paid['revenue'].mean()),
        'customers': int(with_customer['customer_id'].nunique()),
        'repeat_share': float((invoices_per_customer > 1).mean() * 100),
        'period': f"{paid['invoice_ts'].min():%m.%Y} — {paid['invoice_ts'].max():%m.%Y}",
    }

    return {
        'kpi': kpi,
        'monthly': monthly.to_dict(orient='records'),
        'countries': top.to_dict(orient='records'),
        'cohort': cohort.reset_index().to_dict(orient='records'),
        'products': product_revenue.to_dict(orient='records'),
        'generated': date.today().strftime('%d.%m.%Y'),
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Online Retail II — дашборд</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  :root {
    --bg: #f5f6f8; --card: #ffffff; --ink: #1f2937; --muted: #6b7280;
    --accent: #3b6fd4; --accent2: #f2b134; --line: #e5e7eb;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 32px 24px 48px; }
  header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
  h1 { font-size: 28px; margin: 0 0 6px; }
  .sub { color: var(--muted); font-size: 14px; }
  .kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 24px 0; }
  .kpi { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; }
  .kpi .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  .kpi .value { font-size: 26px; font-weight: 700; margin-top: 6px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 8px 8px 0; }
  .card.wide { grid-column: 1 / -1; }
  .card h2 { font-size: 15px; margin: 12px 14px 0; font-weight: 600; }
  .chart { height: 340px; }
  .chart.tall { height: 420px; }
  footer { color: var(--muted); font-size: 13px; margin-top: 24px; }
  @media (max-width: 980px) {
    .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .grid { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Online Retail II: основные метрики</h1>
      <div class="sub">Оплаченные заказы, период __PERIOD__. Данные Kaggle (CC0), британский оптовик.</div>
    </div>
    <div class="sub">Обновлено __GENERATED__</div>
  </header>

  <section class="kpis">
    <div class="kpi"><div class="label">Выручка</div><div class="value" id="kpi-revenue"></div></div>
    <div class="kpi"><div class="label">Заказы</div><div class="value" id="kpi-orders"></div></div>
    <div class="kpi"><div class="label">Средний чек</div><div class="value" id="kpi-aov"></div></div>
    <div class="kpi"><div class="label">Покупатели</div><div class="value" id="kpi-customers"></div></div>
    <div class="kpi"><div class="label">Доля повторных</div><div class="value" id="kpi-repeat"></div></div>
  </section>

  <section class="grid">
    <div class="card wide">
      <h2>Выручка и число заказов по месяцам</h2>
      <div class="chart tall" id="chart-monthly"></div>
    </div>
    <div class="card">
      <h2>Структура выручки по странам</h2>
      <div class="chart" id="chart-country"></div>
    </div>
    <div class="card">
      <h2>Новые и вернувшиеся покупатели</h2>
      <div class="chart" id="chart-cohort"></div>
    </div>
    <div class="card">
      <h2>Средний чек и медиана</h2>
      <div class="chart" id="chart-aov"></div>
    </div>
    <div class="card">
      <h2>Топ-10 товаров по выручке</h2>
      <div class="chart" id="chart-products"></div>
    </div>
  </section>

  <footer>
    Источник: Online Retail II, Kaggle, лицензия CC0 1.0. Только оплаченные заказы; отмены исключены.
    Декабрь 2011 обрезан — данные до 9 декабря.
  </footer>
</div>

<script>
const DATA = __DATA__;
const money = v => v.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) + ' £';
const num = v => v.toLocaleString('ru-RU');
const monthLabel = m => {
  const [y, mm] = m.split('-');
  const names = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
  return names[Number(mm) - 1] + ' ' + y.slice(2);
};

const layout = (extra = {}) => Object.assign({
  margin: { l: 60, r: 24, t: 16, b: 48 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: { family: 'inherit', size: 12, color: '#374151' },
  hoverlabel: { bgcolor: '#111827', font: { color: '#fff' } }
}, extra);
const config = { displayModeBar: false, responsive: true };

document.getElementById('kpi-revenue').textContent = money(DATA.kpi.revenue);
document.getElementById('kpi-orders').textContent = num(DATA.kpi.orders);
document.getElementById('kpi-aov').textContent = money(DATA.kpi.aov);
document.getElementById('kpi-customers').textContent = num(DATA.kpi.customers);
document.getElementById('kpi-repeat').textContent = DATA.kpi.repeat_share.toFixed(1) + ' %';

const months = DATA.monthly.map(r => monthLabel(r.month));

Plotly.newPlot('chart-monthly', [
  {
    x: months, y: DATA.monthly.map(r => r.revenue), type: 'bar', name: 'Выручка',
    marker: { color: '#3b6fd4' }, hovertemplate: '%{x}<br>%{y:,.0f} £<extra></extra>'
  },
  {
    x: months, y: DATA.monthly.map(r => r.orders), type: 'scatter', mode: 'lines+markers',
    name: 'Заказы', yaxis: 'y2', line: { color: '#f2b134', width: 3 },
    hovertemplate: '%{x}<br>%{y} заказов<extra></extra>'
  }
], layout({
  yaxis: { title: 'Выручка, £', gridcolor: '#eef0f3', tickformat: ',.0f' },
  yaxis2: { title: 'Заказы', overlaying: 'y', side: 'right', showgrid: false },
  legend: { orientation: 'h', y: 1.12, x: 0 },
  bargap: 0.35
}), config);

Plotly.newPlot('chart-country', [{
  labels: DATA.countries.map(r => r.country),
  values: DATA.countries.map(r => r.revenue),
  type: 'pie', hole: 0.55,
  marker: { colors: ['#3b6fd4','#5b8def','#7aa7f5','#9cc0f8','#f2b134','#f6c65b','#9aa7b8','#c3ccd8','#dfe5ee'] },
  textinfo: 'percent', hovertemplate: '%{label}<br>%{value:,.0f} £<extra></extra>'
}], layout({ showlegend: true, legend: { orientation: 'v', x: 0.98, y: 0.5 } }), config);

Plotly.newPlot('chart-cohort', [
  { x: DATA.cohort.map(r => monthLabel(r.month)), y: DATA.cohort.map(r => r.new),
     type: 'bar', name: 'Новые', marker: { color: '#3b6fd4' } },
  { x: DATA.cohort.map(r => monthLabel(r.month)), y: DATA.cohort.map(r => r.returning),
     type: 'bar', name: 'Вернувшиеся', marker: { color: '#f2b134' } }
], layout({ barmode: 'stack', yaxis: { title: 'Покупателей', gridcolor: '#eef0f3' },
             legend: { orientation: 'h', y: 1.12, x: 0 } }), config);

Plotly.newPlot('chart-aov', [
  { x: months, y: DATA.monthly.map(r => r.aov), type: 'scatter', mode: 'lines+markers',
     name: 'Средний чек', line: { color: '#3b6fd4', width: 3 } },
  { x: months, y: DATA.monthly.map(r => r.median_check), type: 'scatter', mode: 'lines+markers',
     name: 'Медиана', line: { color: '#f2b134', width: 3, dash: 'dot' } }
], layout({ yaxis: { title: '£', gridcolor: '#eef0f3', tickformat: ',.0f' },
             legend: { orientation: 'h', y: 1.12, x: 0 } }), config);

const products = [...DATA.products].reverse();
Plotly.newPlot('chart-products', [{
  x: products.map(r => r.net), y: products.map(r => r.description), type: 'bar', orientation: 'h',
  marker: { color: '#3b6fd4' }, hovertemplate: '%{y}<br>%{x:,.0f} £<extra></extra>'
}], layout({ margin: { l: 240, r: 24, t: 8, b: 40 },
              xaxis: { title: 'Выручка, £', gridcolor: '#eef0f3', tickformat: ',.0f' } }), config);
</script>
</body>
</html>
"""


def render(payload):
    template = HTML_TEMPLATE.replace('{{', '{').replace('}}', '}')
    html = template.replace('__DATA__', json.dumps(payload, ensure_ascii=False))
    html = html.replace('__PERIOD__', payload['kpi']['period'])
    html = html.replace('__GENERATED__', payload['generated'])
    return html


def main():
    parser = argparse.ArgumentParser(description='Сборка дашборда Online Retail II')
    parser.add_argument('--data', default=DEFAULT_DATA, help='каталог с CSV')
    parser.add_argument('--out', default=DEFAULT_OUT, help='путь к index.html')
    args = parser.parse_args()

    payload = build_payload(args.data)
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write(render(payload))
    print(f'{args.out}: {os.path.getsize(args.out) / 1024:.0f} КБ, '
          f'{len(payload["monthly"])} месяцев, {len(payload["countries"])} стран')


if __name__ == '__main__':
    main()
