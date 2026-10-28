#!/usr/bin/env python3
"""Conservative, credential-free GPU rate-card observer. No composite index."""
import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import html
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_URL = 'https://lambda.ai/instances'
VAST_URL = 'https://vast.ai/pricing'
RUNPOD_URL = 'https://www.runpod.io/pricing'


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', value))).strip()


def parse_lambda(document):
    """Read visible SSR tables, never embedded CMS copies or API example prices."""
    tabs = dict(re.findall(r'<button\b[^>]*aria-controls="([^"]+)"[^>]*>(\d+)x</button>', document))
    panels = re.split(r'<div\b(?=[^>]*role="tabpanel")', document)[1:]
    offers = []
    seen_counts = set()
    for panel in panels:
        panel_id = re.search(r'\bid="([^"]+)"', panel.split('>', 1)[0])
        if not panel_id or panel_id.group(1) not in tabs:
            raise ValueError('Unrecognized instance-count tab association')
        count = int(tabs[panel_id.group(1)])
        before = len(offers)
        seen_counts.add(count)
        table = re.search(r'<table\b[^>]*>(.*?)</table>', panel, re.S)
        if not table or 'PRICE/GPU/HR' not in table.group(1):
            raise ValueError('Missing explicit per-GPU-hour price table')
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table.group(1), re.S):
            cells = {label: plain(value) for label, value in re.findall(r'<(?:td|th)\b[^>]*data-label="([^"]+)"[^>]*>(.*?)</(?:td|th)>', row, re.S)}
            if not cells:
                continue
            gpu, memory, price = cells['Plan'], cells['VRAM/GPU'], cells['PRICE/GPU/HR*']
            if not re.fullmatch(r'\d+ GB', memory) or not re.fullmatch(r'\$\d+\.\d{2}', price):
                raise ValueError('Unexpected memory or USD price units')
            amount = Decimal(price[1:])
            if not Decimal('0.01') <= amount <= Decimal('1000'):
                raise ValueError('Price outside validation bounds')
            memory_gb = int(memory.split()[0])
            offers.append({'id': re.sub('[^a-z0-9]+', '-', f'lambda-{gpu}-{memory_gb}gb-{count}x'.lower()).strip('-'),
                'gpu': gpu, 'memory_gb': memory_gb, 'gpu_count': count,
                'price_usd_per_gpu_hour': float(amount), 'price_usd_per_instance_hour': float(amount * count),
                'currency': 'USD', 'pricing_type': 'on-demand', 'region': None,
                'availability': 'not_reported', 'vcpu': int(cells['vCPUs']),
                'ram': cells['RAM'], 'storage': cells['STORAGE']})
        if len(offers) == before:
            raise ValueError('Empty instance-count pricing table')
    if seen_counts != {1, 2, 4, 8} or set(int(v) for v in tabs.values()) != {1, 2, 4, 8} or len(offers) < 10:
        raise ValueError('Incomplete or changed Lambda pricing page')
    if len({x['id'] for x in offers}) != len(offers):
        raise ValueError('Duplicate hardware/configuration')
    return offers


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'TokenIndex-GPURateObserver/1.0 (+https://harni555.github.io/agent-token-index/)'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f'HTTP {response.status}')
        return response.read(2_000_000).decode('utf-8')


def build_snapshot(previous=None, now=None, fetcher=fetch):
    now = now or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    previous = previous or {}
    old = {p['id']: p for p in previous.get('providers', [])}
    provider = {'id': 'lambda', 'name': 'Lambda', 'url': LAMBDA_URL, 'status': 'current',
        'observed_at': now, 'provider_updated_at': None, 'last_attempt_at': now, 'error': None,
        'disclosures': ['Posted USD per-GPU-hour on-demand rates, not executed transaction prices or guaranteed capacity.',
            'Instance price is calculated as the posted per-GPU rate multiplied by GPU count. Multi-GPU discounts remain separate configurations.',
            'Prices exclude applicable sales tax/VAT/GST. Storage specifications describe the advertised instance, not all possible ancillary charges.',
            'Source provides no publication timestamp; observed_at records retrieval only. Regional availability requires authenticated Lambda API access.']}
    try:
        document = fetcher(LAMBDA_URL)
        provider['offers'] = parse_lambda(document)
        provider['source_sha256'] = hashlib.sha256(document.encode('utf-8')).hexdigest()
    except Exception as exc:
        if old.get('lambda', {}).get('offers'):
            provider = copy.deepcopy(old['lambda'])
            provider['status'] = 'stale'
        else:
            provider['status'] = 'unavailable'
            provider['observed_at'] = None
            provider['offers'] = []
        provider['last_attempt_at'] = now
        provider['error'] = f'Rate retrieval/validation failed; last-good data retained where available: {type(exc).__name__}: {exc}'[:500]
    providers = [provider]
    for ident, name, url, status, reason in [
        ('vast', 'Vast.ai', VAST_URL, 'license_required', 'The official public feed allows attributed display, but bulk collection, redistribution, or use in an index/benchmark/derivative product requires a data license. Not collected or archived pending permission.'),
        ('runpod', 'Runpod', RUNPOD_URL, 'unavailable', 'No verified unattended public collector configured. Direct pricing-page retrieval was blocked during setup; the official catalog API documents bearer authentication. No credentials or API example prices used.')]:
        providers.append({'id': ident, 'name': name, 'url': url, 'status': status,
            'observed_at': None, 'provider_updated_at': None, 'last_attempt_at': None,
            'error': reason, 'offers': [], 'disclosures': [reason]})
    return {'schema_version': 1, 'generated_at': now, 'unit': 'USD/GPU-hour',
        'methodology': 'Observed provider rate cards, not a GPU price index. No cross-hardware composite, capacity inference, token-cost conversion, or reconstructed history.',
        'providers': providers}


def save_snapshot(snapshot, output, archive):
    output, archive = Path(output), Path(archive)
    output.parent.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    if output.exists():
        old = json.loads(output.read_text())
        stamp = re.sub(r'[^0-9TZ]', '', old['generated_at'])
        path = archive / f'{stamp}.json'
        if not path.exists():
            path.write_text(json.dumps(old, indent=2) + '\n')
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, indent=2) + '\n')
    temp.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'public/data/gpu-prices.json')
    parser.add_argument('--archive', type=Path, default=ROOT / 'data/gpu-snapshots')
    args = parser.parse_args()
    previous = json.loads(args.output.read_text()) if args.output.exists() else None
    snapshot = build_snapshot(previous)
    save_snapshot(snapshot, args.output, args.archive)
    for provider in snapshot['providers']:
        print(f"{provider['name']}: {provider['status']} ({len(provider['offers'])} configurations)")
    if snapshot['providers'][0]['status'] != 'current':
        raise SystemExit(1)

if __name__ == '__main__':
    main()
