import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('gpu_prices', Path(__file__).parents[1] / 'scripts/gpu_prices.py')
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)


def fixture():
    tabs, panels = [], []
    for count in [8, 4, 2, 1]:
        tabs.append(f'<button role="tab" aria-controls="p{count}">{count}x</button>')
        rows = []
        for model, memory, price in [('NVIDIA H100 SXM', 80, '4.29'), ('NVIDIA B200 SXM6', 180, '6.99'), ('NVIDIA A6000', 48, '1.09')]:
            cells = {'Plan':model, 'VRAM/GPU':f'{memory} GB', 'vCPUs':'26', 'RAM':'225 GiB', 'STORAGE':'1 TiB SSD', 'PRICE/GPU/HR*':f'${price}'}
            rows.append('<tr>' + ''.join(f'<td data-label="{k}">{v}</td>' for k,v in cells.items()) + '</tr>')
        panels.append(f'<div role="tabpanel" id="p{count}"><table><thead>PRICE/GPU/HR*</thead>{"".join(rows)}</table></div>')
    return ''.join(tabs + panels)


class GPUPriceTests(unittest.TestCase):
    def test_per_gpu_instance_arithmetic(self):
        offers = gpu.parse_lambda(fixture())
        self.assertEqual(len(offers), 12)
        h100 = next(x for x in offers if x['gpu'] == 'NVIDIA H100 SXM' and x['gpu_count'] == 8)
        self.assertEqual(h100['price_usd_per_gpu_hour'], 4.29)
        self.assertEqual(h100['price_usd_per_instance_hour'], 34.32)
        self.assertEqual(h100['memory_gb'], 80)
        self.assertEqual(h100['availability'], 'not_reported')

    def test_schema_change_fails_closed(self):
        for bad in [fixture().replace('PRICE/GPU/HR', 'PRICE/INSTANCE/HR'), fixture().replace('$4.29', '$0.00'), fixture().replace('80 GB','80 GiB'), '<html>Login</html>']:
            with self.assertRaises((ValueError, KeyError)):
                gpu.parse_lambda(bad)

    def test_failure_preserves_actual_observation(self):
        good = gpu.build_snapshot(now='2026-10-28T00:00:00Z', fetcher=lambda _: fixture())
        def fail(_):
            raise OSError('network unavailable')
        bad = gpu.build_snapshot(good, now='2026-10-29T00:00:00Z', fetcher=fail)
        before, after = good['providers'][0], bad['providers'][0]
        self.assertEqual(after['status'], 'stale')
        self.assertEqual(after['observed_at'], before['observed_at'])
        self.assertEqual(after['offers'], before['offers'])
        self.assertNotEqual(after['last_attempt_at'], before['last_attempt_at'])
        self.assertEqual(before['status'], 'current')

    def test_missing_source_is_not_zero(self):
        snapshot = gpu.build_snapshot(fetcher=lambda _: '<html>Blocked</html>')
        self.assertEqual(snapshot['providers'][0]['status'], 'unavailable')
        self.assertIsNone(snapshot['providers'][0]['observed_at'])
        self.assertEqual(snapshot['providers'][0]['offers'], [])
        self.assertEqual(snapshot['providers'][1]['status'], 'license_required')
        self.assertEqual(snapshot['providers'][1]['offers'], [])

    def test_first_snapshot_no_fake_history_then_archives_previous(self):
        with tempfile.TemporaryDirectory() as root:
            output, archive = Path(root)/'data.json', Path(root)/'archive'
            one = gpu.build_snapshot(now='2026-10-28T00:00:00Z', fetcher=lambda _: fixture())
            gpu.save_snapshot(one, output, archive)
            self.assertEqual(list(archive.iterdir()), [])
            two = gpu.build_snapshot(one, now='2026-10-29T00:00:00Z', fetcher=lambda _: fixture())
            gpu.save_snapshot(two, output, archive)
            self.assertEqual(len(list(archive.iterdir())), 1)
            self.assertEqual(json.loads(next(archive.iterdir()).read_text()), one)
            self.assertEqual(json.loads(output.read_text()), two)

if __name__ == '__main__':
    unittest.main()
