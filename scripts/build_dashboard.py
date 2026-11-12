"""Сборка статического дашборда по данным интернет-магазина.

Читает CSV из проекта sql-retail-case (или из каталога, указанного в --data),
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

MONTHS_RU = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
             'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def load_data(data_dir):
    orders = pd.read_csv(os.path.join(data_dir, 'orders.csv'), parse_dates=['order_ts'])
    items = pd.read_csv(os.path.join(data_dir, 'order_items.csv'))
    products = pd.read_csv(os.path.join(data_dir, 'products.csv'))
    customers = pd.read_csv(os.path.join(data_dir, 'customers.csv'))
    return orders, items, products, customers


def monthly_label(dates):
    return dates.dt.strftime('%Y-%m')


def build_payload(data_dir):
    orders, items, products, customers = load_data(data_dir)

    paid = orders[orders['status'] == 'paid'].copy()
    lines = paid.merge(items, on='order_id')
    lines['net'] = lines['quantity'] * lines['unit_price'] * (1 - lines['discount'])

    order_revenue = lines.groupby('order_id')['net'].sum().rename('revenue')
    paid = paid.merge(order_revenue, on='order_id')
    paid['month'] = monthly_label(paid['order_ts'])

    monthly = paid.groupby('month').agg(orders=('order_id', 'size'),
                                        revenue=('revenue', 'sum'),
                                        aov=('revenue', 'mean'),
                                        median_check=('revenue', 'median')).reset_index()

    category = (lines.merge(products, on='product_id')
                .groupby('category', as_index=False)['net'].sum()
                .sort_values('net', ascending=False))

    first_order = paid.groupby('customer_id')['order_ts'].min().rename('first_ts')
    paid = paid.merge(first_order, on='customer_id')
    paid['is_new'] = paid['order_ts'].dt.month == paid['first_ts'].dt.month
    active = paid.groupby(['month', 'customer_id']).agg(is_new=('is_new', 'max')).reset_index()
    cohort = active.groupby('month').agg(new=('is_new', 'sum'), customers=('customer_id', 'nunique'))
    cohort['returning'] = cohort['customers'] - cohort['new']

    product_revenue = (lines.merge(products, on='product_id')
                       .groupby(['name', 'category'], as_index=False)['net'].sum()
                       .sort_values('net', ascending=False).head(10))

    repeat_customers = paid.groupby('customer_id').size()
    kpi = {
        'revenue': float(paid['revenue'].sum()),
        'orders': int(len(paid)),
        'aov': float(paid['revenue'].mean()),
        'customers': int(paid['customer_id'].nunique()),
        'repeat_share': float((repeat_customers > 1).mean() * 100),
        'period': f"{paid['order_ts'].min():%m.%Y} — {paid['order_ts'].max():%m.%Y}",
    }

    return {
        'kpi': kpi,
        'monthly': monthly.to_dict(orient='records'),
        'category': category.to_dict(orient='records'),
        'cohort': cohort.reset_index().to_dict(orient='records'),
        'products': product_revenue.to_dict(orient='records'),
        'generated': date.today().strftime('%d.%m.%Y'),
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Дашборд интернет-магазина</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  :root {{
    --bg: #f5f6f8; --card: #ffffff; --ink: #1f2937; --muted: #6b7280;
    --accent: #3b6fd4; --accent2: #f2b134; --line: #e5e7eb;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }}
  .wrap {{ max-width: 1240px; margin: 0 auto; padding: 32px 24px 48px; }}
  header {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }}
  h1 {{ font-size: 28px; margin: 0 0 6px; }}
  .sub {{ color: var(--muted); font-size: 14px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 24px 0; }}
  .kpi {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; }}
  .kpi .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
  .kpi .value {{ font-size: 26px; font-weight: 700; margin-top: 6px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 8px 8px 0; }}
  .card.wide {{ grid-column: 1 / -1; }}
  .card h2 {{ font-size: 15px; margin: 12px 14px 0; font-weight: 600; }}
  .chart {{ height: 340px; }}
  .chart.tall {{ height: 420px; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 24px; }}
  @media (max-width: 980px) {{
    .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Интернет-магазин: основные метрики</h1>
      <div class="sub">Оплаченные заказы, период __PERIOD__. Синтетические данные учебного кейса.</div>
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
      <h2>Структура выручки по категориям</h2>
      <div class="chart" id="chart-category"></div>
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
    Источник: синтетические данные проекта sql-retail-case (seed=42). Метрики считаются по оплаченным заказам.
  </footer>
</div>

<script>
const DATA = __DATA__;
const rub = v => v.toLocaleString('ru-RU', {{ maximumFractionDigits: 0 }}) + ' ₽';
const num = v => v.toLocaleString('ru-RU');
const monthLabel = m => {{
  const [y, mm] = m.split('-');
  const names = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
  return names[Number(mm) - 1] + ' ' + y.slice(2);
}};

const layout = (extra = {{}}) => Object.assign({{
  margin: {{ l: 56, r: 24, t: 16, b: 48 }},
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: {{ family: 'inherit', size: 12, color: '#374151' }},
  hoverlabel: {{ bgcolor: '#111827', font: {{ color: '#fff' }} }}
}}, extra);
const config = {{ displayModeBar: false, responsive: true }};

document.getElementById('kpi-revenue').textContent = rub(DATA.kpi.revenue);
document.getElementById('kpi-orders').textContent = num(DATA.kpi.orders);
document.getElementById('kpi-aov').textContent = rub(DATA.kpi.aov);
document.getElementById('kpi-customers').textContent = num(DATA.kpi.customers);
document.getElementById('kpi-repeat').textContent = DATA.kpi.repeat_share.toFixed(1) + ' %';

const months = DATA.monthly.map(r => monthLabel(r.month));

Plotly.newPlot('chart-monthly', [
  {{
    x: months, y: DATA.monthly.map(r => r.revenue), type: 'bar', name: 'Выручка',
    marker: {{ color: '#3b6fd4' }}, hovertemplate: '%{{x}}<br>%{{y:,.0f}} ₽<extra></extra>'
  }},
  {{
    x: months, y: DATA.monthly.map(r => r.orders), type: 'scatter', mode: 'lines+markers',
    name: 'Заказы', yaxis: 'y2', line: {{ color: '#f2b134', width: 3 }},
    hovertemplate: '%{{x}}<br>%{{y}} заказов<extra></extra>'
  }}
], layout({{
  yaxis: {{ title: 'Выручка, ₽', gridcolor: '#eef0f3', tickformat: ',.0f' }},
  yaxis2: {{ title: 'Заказы', overlaying: 'y', side: 'right', showgrid: false }},
  legend: {{ orientation: 'h', y: 1.12, x: 0 }},
  bargap: 0.35
}}), config);

Plotly.newPlot('chart-category', [{{
  labels: DATA.category.map(r => r.category),
  values: DATA.category.map(r => r.net),
  type: 'pie', hole: 0.55,
  marker: {{ colors: ['#3b6fd4','#5b8def','#7aa7f5','#9cc0f8','#f2b134','#f6c65b','#9aa7b8','#c3ccd8'] }},
  textinfo: 'percent', hovertemplate: '%{{label}}<br>%{{value:,.0f}} ₽<extra></extra>'
}}], layout({{ showlegend: true, legend: {{ orientation: 'v', x: 0.98, y: 0.5 }} }}), config);

Plotly.newPlot('chart-cohort', [
  {{ x: DATA.cohort.map(r => monthLabel(r.month)), y: DATA.cohort.map(r => r.new),
     type: 'bar', name: 'Новые', marker: {{ color: '#3b6fd4' }} }},
  {{ x: DATA.cohort.map(r => monthLabel(r.month)), y: DATA.cohort.map(r => r.returning),
     type: 'bar', name: 'Вернувшиеся', marker: {{ color: '#f2b134' }} }}
], layout({{ barmode: 'stack', yaxis: {{ title: 'Покупателей', gridcolor: '#eef0f3' }},
             legend: {{ orientation: 'h', y: 1.12, x: 0 }} }}), config);

Plotly.newPlot('chart-aov', [
  {{ x: months, y: DATA.monthly.map(r => r.aov), type: 'scatter', mode: 'lines+markers',
     name: 'Средний чек', line: {{ color: '#3b6fd4', width: 3 }} }},
  {{ x: months, y: DATA.monthly.map(r => r.median_check), type: 'scatter', mode: 'lines+markers',
     name: 'Медиана', line: {{ color: '#f2b134', width: 3, dash: 'dot' }} }}
], layout({{ yaxis: {{ title: '₽', gridcolor: '#eef0f3', tickformat: ',.0f' }},
             legend: {{ orientation: 'h', y: 1.12, x: 0 }} }}), config);

const products = [...DATA.products].reverse();
Plotly.newPlot('chart-products', [{{
  x: products.map(r => r.net), y: products.map(r => r.name), type: 'bar', orientation: 'h',
  marker: {{ color: '#3b6fd4' }}, hovertemplate: '%{{y}}<br>%{{x:,.0f}} ₽<extra></extra>'
}}], layout({{ margin: {{ l: 190, r: 24, t: 8, b: 40 }},
              xaxis: {{ title: 'Выручка, ₽', gridcolor: '#eef0f3', tickformat: ',.0f' }} }}), config);
</script>
</body>
</html>
"""


def render(payload):
    period = payload['kpi']['period']
    generated = payload['generated']
    data_json = json.dumps(payload, ensure_ascii=False)
    # в шаблоне фигурные скобки CSS/JS удвоены для .format(); здесь они не нужны
    template = HTML_TEMPLATE.replace('{{', '{').replace('}}', '}')
    html = template.replace('__DATA__', data_json)
    html = html.replace('__PERIOD__', period).replace('__GENERATED__', generated)
    return html


def main():
    parser = argparse.ArgumentParser(description='Сборка дашборда интернет-магазина')
    parser.add_argument('--data', default=DEFAULT_DATA, help='каталог с CSV')
    parser.add_argument('--out', default=DEFAULT_OUT, help='путь к index.html')
    args = parser.parse_args()

    payload = build_payload(args.data)
    html = render(payload)
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write(html)
    print(f'{args.out}: {os.path.getsize(args.out) / 1024:.0f} КБ, '
          f'{len(payload["monthly"])} месяцев, {len(payload["category"])} категорий')


if __name__ == '__main__':
    main()
