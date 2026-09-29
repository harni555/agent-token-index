"""OpenRouter aggregate research collector. Python standard library only."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'public' / 'data' / 'index.json'
START = dt.date(2025, 1, 1)
CATEGORIES = ('personal-agent', 'cli-agent', 'cloud-agent', 'ide-extension')
GROUPS = {'PATI': ('personal-agent',), 'CATI': ('cli-agent', 'cloud-agent'),
          'BAWI': ('personal-agent', 'cli-agent', 'cloud-agent'), 'IDE': ('ide-extension',)}

def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
        raise ValueError('Expected nonnegative integer count')
    return int(value)

def last_sunday(today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return today - dt.timedelta(days=today.weekday() + 1)

def windows(end):
    start = START
    while start <= end:
        finish = min(start + dt.timedelta(days=6-start.weekday()), end)
        yield start.isoformat(), finish.isoformat()
        start = finish + dt.timedelta(days=1)

def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    tmp.replace(path)

def validate_payload(endpoint, params, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('Invalid response envelope')
    if endpoint == 'models':
        if not payload['data'] or any(not r.get('id') or not isinstance(r.get('pricing'), dict) for r in payload['data']):
            raise ValueError('Invalid model catalog')
        return
    meta = payload.get('meta', {})
    if meta.get('start_date') != params['start_date'] or meta.get('end_date') != params['end_date']:
        raise ValueError('Upstream changed requested date window')
    dt.datetime.fromisoformat(meta['as_of'].replace('Z', '+00:00'))
    seen = set()
    for row in payload['data']:
        number(row['total_tokens'])
        if endpoint.endswith('app-rankings'):
            key = str(row['app_id'])
            number(row['total_requests'])
            if not isinstance(row.get('app_name'), str):
                raise ValueError('Missing app name')
            if number(row['rank']) < int(params.get('offset', 0)) + 1:
                raise ValueError('Unexpected rank/offset')
        else:
            key = (row['date'], row['model_permaslug'])
            if not params['start_date'] <= row['date'] <= params['end_date']:
                raise ValueError('Out-of-window model row')
        if key in seen:
            raise ValueError('Duplicate upstream row')
        seen.add(key)

def query_id(endpoint, params):
    return hashlib.sha256(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()[:24]

def snapshot(endpoint, params, payload):
    validate_payload(endpoint, params, payload)
    envelope = {'endpoint': endpoint, 'params': params, 'fetchedAt': utcnow(), 'payload': payload}
    body = json.dumps(envelope, sort_keys=True, ensure_ascii=False).encode()
    digest = hashlib.sha256(body).hexdigest()
    folder = RAW / query_id(endpoint, params)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest + '.json')
    if not path.exists():
        with path.open('xb') as f:
            f.write(body)
    return envelope

def cached(endpoint, params):
    folder = RAW / query_id(endpoint, params)
    if not folder.exists():
        return None
    items = []
    for p in folder.glob('*.json'):
        body = p.read_bytes()
        if hashlib.sha256(body).hexdigest() != p.stem:
            raise ValueError('Snapshot checksum mismatch: ' + str(p))
        item = json.loads(body)
        validate_payload(endpoint, params, item['payload'])
        items.append(item)
    return max(items, key=lambda x: x['fetchedAt']) if items else None

class Client:
    def __init__(self, budget=450):
        self.key = os.environ.get('OPENROUTER_API_KEY')
        self.remaining = budget
        self.previous = 0

    def get(self, endpoint, params, force=False):
        old = cached(endpoint, params)
        if old and not force:
            return old
        if endpoint != 'models' and not self.key:
            raise RuntimeError('OPENROUTER_API_KEY is missing. Add the repository Actions secret and run Refresh data.')
        for attempt in range(4):
            if self.remaining <= 0:
                raise RuntimeError('Safe request budget reached; snapshots retained. Resume after daily quota resets.')
            time.sleep(max(0, 2.15-(time.monotonic()-self.previous)))
            self.remaining -= 1
            self.previous = time.monotonic()
            headers = {'Accept': 'application/json', 'User-Agent': 'AgentTokenIndex/1.0'}
            if self.key and endpoint != 'models':
                headers['Authorization'] = 'Bearer ' + self.key
            url = 'https://openrouter.ai/api/v1/' + endpoint + '?' + urllib.parse.urlencode(params)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                    payload = json.load(r)
                return snapshot(endpoint, params, payload)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    # Avoid repeatedly spending an exhausted daily allocation.
                    raise RuntimeError('OpenRouter quota reached; snapshots retained. Resume after quota reset.') from None
                if e.code < 500 or attempt == 3:
                    raise RuntimeError('OpenRouter HTTP ' + str(e.code) + '; prior published data preserved') from None
            except (TimeoutError, urllib.error.URLError):
                if attempt == 3:
                    raise RuntimeError('OpenRouter unavailable; prior published data preserved') from None
            time.sleep(2 ** attempt)

def app_params(start, end, category, offset=0):
    return {'start_date': start, 'end_date': end, 'subcategory': category,
            'sort': 'popular', 'limit': 100, 'offset': offset}

def merge_apps(categories, selected):
    merged = {}
    for category in selected:
        for row in categories[category]:
            key = str(row['app_id'])
            if key in merged:
                prior = merged[key]
                if (number(prior['total_tokens']), number(prior['total_requests'])) != (number(row['total_tokens']), number(row['total_requests'])):
                    raise ValueError('Inconsistent overlapping app totals; refusing double counting')
                prior['categories'] = sorted(set(prior['categories'] + [category]))
            else:
                merged[key] = {**row, 'categories': [category]}
    return sorted(merged.values(), key=lambda r: number(r['total_tokens']), reverse=True)

def growth(now, prior):
    return (now / prior - 1) * 100 if now is not None and prior is not None and prior > 0 else None

def derive(weeks):
    baselines = {}
    for key in GROUPS:
        valid = [w for w in weeks if w['completeWeek'] and w['series'][key]['tokens'] is not None and int(w['series'][key]['tokens']) > 0]
        jan = [w for w in valid if w['start'].startswith('2025-01') and w['end'].startswith('2025-01')]
        # A Jan baseline requires all three complete Monday-Sunday January weeks.
        baseweeks = jan if len(jan) == 3 else valid[:1]
        base = sum(int(w['series'][key]['tokens']) for w in baseweeks)/len(baseweeks) if baseweeks else None
        baselines[key] = {'value': base, 'label': 'Jan 2025 weekly mean = 100' if len(jan)==3 else 'First available complete week = 100', 'start': baseweeks[0]['start'] if baseweeks else None}
        for i, week in enumerate(weeks):
            s = week['series'][key]
            val = int(s['tokens']) if s['tokens'] is not None and week['completeWeek'] else None
            def prev(n):
                if i < n or not weeks[i-n]['completeWeek']:
                    return None
                p = weeks[i-n]['series'][key]['tokens']
                return int(p) if p is not None else None
            s['index'] = val / base * 100 if val is not None and base else None
            s['wow'] = growth(val, prev(1))
            s['fourWeekGrowth'] = growth(val, prev(4))
            vals = [prev(3), prev(2), prev(1), val]
            s['ma4'] = sum(vals)/4 if all(v is not None for v in vals) else None
            s['indexMa4'] = s['ma4']/base*100 if s['ma4'] is not None and base else None
    return baselines

def rebuild(end=None):
    end = end or last_sunday()
    daily, sources = {}, []
    # Daily models use calendar-month requests, so completed-month snapshots are reusable.
    day = START
    while day <= end:
        next_month = (day.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
        finish = min(next_month-dt.timedelta(days=1), end)
        p = {'start_date': day.isoformat(), 'end_date': finish.isoformat()}
        item = cached('datasets/rankings-daily', p)
        if not item:
            raise ValueError('Missing model snapshot for ' + day.isoformat())
        sources.append({'endpoint': item['endpoint'], 'asOf': item['payload']['meta']['as_of'], 'queryId': query_id(item['endpoint'], p)})
        for row in item['payload']['data']:
            daily.setdefault(row['date'], []).append(row)
        day = next_month
    weeks = []
    for start, finish in windows(end):
        categories, caps = {}, []
        for category in CATEGORIES:
            p = app_params(start, finish, category)
            item = cached('datasets/app-rankings', p)
            if not item:
                raise ValueError('Missing app snapshot for ' + start + ' ' + category)
            rows = item['payload']['data'][:]
            sources.append({'endpoint': item['endpoint'], 'asOf': item['payload']['meta']['as_of'], 'queryId': query_id(item['endpoint'], p)})
            if len(rows) == 100:
                p2 = app_params(start, finish, category, 100)
                second = cached('datasets/app-rankings', p2)
                if not second:
                    raise ValueError('Missing second ranking page')
                rows += second['payload']['data']
                sources.append({'endpoint': second['endpoint'], 'asOf': second['payload']['meta']['as_of'], 'queryId': query_id(second['endpoint'], p2)})
                if len(second['payload']['data']) == 100:
                    caps.append(category)
            if len({str(r['app_id']) for r in rows}) != len(rows):
                raise ValueError('Duplicate app across ranking pages')
            categories[category] = rows
        days = (dt.date.fromisoformat(finish)-dt.date.fromisoformat(start)).days+1
        dates = [(dt.date.fromisoformat(start)+dt.timedelta(days=i)).isoformat() for i in range(days)]
        if any(d not in daily for d in dates):
            raise ValueError('Missing model days: refusing incomplete denominator')
        models = {}
        for d in dates:
            for row in daily[d]:
                name = row['model_permaslug']
                models[name] = models.get(name, 0)+number(row['total_tokens'])
        total = sum(models.values())
        series = {}
        for key, selected in GROUPS.items():
            apps = merge_apps(categories, selected)
            # Empty subcategories can mean unavailable history; never infer zero.
            available = all(categories[c] for c in selected)
            tokens = sum(number(r['total_tokens']) for r in apps) if available else None
            requests = sum(number(r['total_requests']) for r in apps) if available else None
            series[key] = {'tokens': str(tokens) if tokens is not None else None,
                           'requests': str(requests) if requests is not None else None,
                           'tokensPerRequest': tokens/requests if requests else None,
                           'share': tokens/total*100 if tokens is not None and total else None,
                           'appCount': len(apps), 'capped': any(c in caps for c in selected),
                           'apps': [{'id': str(r['app_id']), 'name': r['app_name'], 'tokens': str(number(r['total_tokens'])), 'requests': str(number(r['total_requests'])), 'categories': r['categories']} for r in apps[:20]]}
        weeks.append({'start': start, 'end': finish, 'completeWeek': days==7,
                      'platformTokens': str(total), 'series': series,
                      'models': [{'name': name, 'tokens': str(tokens), 'share': tokens/total*100 if total else None} for name,tokens in sorted(models.items(), key=lambda p:p[1], reverse=True)]})
    baselines = derive(weeks)
    price = cached('models', {})
    doc = {'schemaVersion': 1, 'status': 'ready', 'generatedAt': utcnow(), 'requestedStart': START.isoformat(),
           'dataThrough': end.isoformat(), 'weeks': weeks, 'baselines': baselines,
           'pricesAsOf': price['fetchedAt'] if price else None, 'sources': sources,
           'coverage': {'message': 'Observed public ranked apps only. Historical classifications reflect the taxonomy at retrieval. Model mix covers public OpenRouter traffic, not agent-only traffic.'}}
    validate_index(doc, require_fresh=True)
    atomic_json(OUT, doc)
    atomic_json(ROOT/'data'/'derived'/'index.json', doc)
    print('Published data through ' + end.isoformat())

def validate_index(doc, require_fresh=False):
    if doc['schemaVersion'] != 1:
        raise ValueError('Unknown schema')
    if not doc['weeks']:
        if doc['status'] != 'awaiting_credentials' or doc['dataThrough'] is not None or require_fresh:
            raise ValueError('Empty or uninitialized dataset')
        return
    if doc['status'] != 'ready' or doc['dataThrough'] != doc['weeks'][-1]['end']:
        raise ValueError('Invalid data-through date')
    previous = None
    for week in doc['weeks']:
        start, end = dt.date.fromisoformat(week['start']), dt.date.fromisoformat(week['end'])
        if previous and start != previous+dt.timedelta(days=1):
            raise ValueError('Gap in weekly calendar')
        previous = end
        denominator = number(week['platformTokens'])
        for s in week['series'].values():
            if s['tokens'] is not None:
                number(s['tokens']); number(s['requests'])
                if denominator <= 0 or not 0 <= s['share'] <= 100:
                    raise ValueError('Agent/platform population mismatch; share outside 0-100%')
    if require_fresh and (dt.datetime.now(dt.timezone.utc).date()-dt.date.fromisoformat(doc['dataThrough'])).days > 9:
        raise ValueError('Stale data: publication blocked')
    if require_fresh and any(doc['weeks'][-1]['series'][k]['tokens'] is None for k in GROUPS):
        raise ValueError('Latest source window is empty for a required category; publication blocked')

def collect(prices_only=False, budget=450):
    client = Client(budget)
    client.get('models', {}, force=True)
    if prices_only:
        if OUT.exists():
            doc = json.loads(OUT.read_text(encoding='utf-8'))
            if not doc['weeks']:
                doc['pricesAsOf'] = cached('models', {})['fetchedAt']
                atomic_json(OUT, doc)
        return
    end = last_sunday()
    day = START
    while day <= end:
        next_month = (day.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
        finish = min(next_month-dt.timedelta(days=1), end)
        client.get('datasets/rankings-daily', {'start_date': day.isoformat(), 'end_date': finish.isoformat()}, force=(end-finish).days < 28)
        day = next_month
    for start, finish in windows(end):
        force = (end-dt.date.fromisoformat(finish)).days < 28
        for category in CATEGORIES:
            first = client.get('datasets/app-rankings', app_params(start, finish, category), force=force)
            if len(first['payload']['data']) == 100:
                client.get('datasets/app-rankings', app_params(start, finish, category, 100), force=force)
        print('Collected ' + start + ' to ' + finish, flush=True)
    rebuild(end)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['refresh', 'prices', 'rebuild', 'validate'])
    parser.add_argument('--require-fresh', action='store_true')
    parser.add_argument('--budget', type=int, default=450)
    args = parser.parse_args()
    if args.command in ('refresh', 'prices'):
        collect(args.command=='prices', args.budget)
    elif args.command == 'rebuild':
        rebuild()
    else:
        validate_index(json.loads(OUT.read_text(encoding='utf-8')), args.require_fresh)
        print('Data validation passed')
