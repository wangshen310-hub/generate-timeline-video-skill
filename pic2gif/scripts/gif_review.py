"""Subject-independent planning, measurements and hash-bound GIF review."""
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} needs nonempty text')


def number(value, label, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{label} must be finite and >= {minimum}')


def vector(value):
    values = value if isinstance(value, list) else [value]
    if not values or len(values) > 4:
        raise ValueError('Measurements need a scalar or a vector of 1-4 components')
    for v in values:
        if type(v) not in (int, float) or not math.isfinite(v):
            raise ValueError('Measurement components must be finite numbers')
    return values


def plan_check(data):
    plan = data.get('plan')
    if not isinstance(plan, dict):
        raise ValueError('Add a plan before source review; legacy manifests can still render previews')
    if plan.get('intent') not in ('motion', 'still'):
        raise ValueError('plan.intent must be motion or still')
    if plan.get('source_mode') not in ('generated', 'provided'):
        raise ValueError('plan.source_mode must be generated or provided')
    text(plan.get('summary'), 'plan.summary')
    for i, frame in enumerate(data['frames']):
        text(frame.get('state'), f'frames[{i}].state')
        if plan['source_mode'] == 'generated':
            text(frame.get('prompt'), f'frames[{i}].prompt')
    if 'max_bytes' in plan:
        if type(plan['max_bytes']) is not int or plan['max_bytes'] <= 0:
            raise ValueError('plan.max_bytes must be a positive integer')
    ids = set()
    for group in ('measurements', 'fixed_regions'):
        items = plan.get(group, [])
        if not isinstance(items, list):
            raise ValueError(f'plan.{group} must be a list')
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f'Invalid {group} item')
            text(item.get('id'), 'check id')
            if item['id'] in ids:
                raise ValueError('Check ids must be unique')
            ids.add(item['id'])
            if group == 'measurements':
                for key in ('property', 'space', 'unit'):
                    text(item.get(key), key)
                expected = item.get('expected')
                if not isinstance(expected, list) or len(expected) != len(data['frames']):
                    raise ValueError('expected must contain one value per displayed frame')
                widths = {len(vector(v)) for v in expected}
                if len(widths) != 1:
                    raise ValueError('Measurement dimensions must match')
                number(item.get('tolerance'), 'tolerance')
                for key in ('min_speed', 'max_speed', 'max_acceleration'):
                    if key in item:
                        number(item[key], key)
                if item.get('min_speed', 0) > item.get('max_speed', math.inf):
                    raise ValueError('min_speed exceeds max_speed')
                violations, _ = measure(item, expected, data)
                if violations:
                    raise ValueError('Planned values contradict limits: ' + '; '.join(violations))
            else:
                rect = item.get('rect')
                if not isinstance(rect, list) or len(rect) != 4:
                    raise ValueError('rect must be normalized [x,y,width,height]')
                for v in rect:
                    number(v, 'rect component')
                x, y, w, h = rect
                if w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
                    raise ValueError('rect must lie inside the normalized output canvas')
                number(item.get('max_mae'), 'max_mae')
                if item['max_mae'] > 255:
                    raise ValueError('max_mae is on the 0-255 RGB scale')
    return {'valid': True, 'intent': plan['intent'], 'frames': len(data['frames']),
            'duration_ms': sum(f['duration_ms'] for f in data['frames']),
            'note': 'Checks plan structure and declared limits; does not prove generation history or visual quality'}


def norm(v):
    return math.sqrt(sum(x * x for x in v))


def measure(check, values, data):
    """Use exposure of frame i for i->i+1, including the cyclic closing edge."""
    values = [vector(v) for v in values]
    expected = [vector(v) for v in check['expected']]
    if len(values) != len(expected) or any(len(a) != len(b) for a, b in zip(values, expected)):
        raise ValueError('Observed values must match expected count and dimensionality')
    errors = []
    for i, (a, b) in enumerate(zip(values, expected)):
        if norm([x - y for x, y in zip(a, b)]) > check['tolerance']:
            errors.append(f"{check['id']} frame {i}: expected-value tolerance exceeded")
    velocities, dt, edges = [], [], []
    count = len(values) if data.get('loop', True) and len(values) > 1 else len(values) - 1
    for i in range(count):
        j = (i + 1) % len(values)
        seconds = data['frames'][i]['duration_ms'] / 1000
        v = [(b - a) / seconds for a, b in zip(values[i], values[j])]
        speed = norm(v)
        velocities.append(v)
        dt.append(seconds)
        edges.append({'from': i, 'to': j, 'seconds': seconds, 'speed': speed, 'velocity': v})
        if speed < check.get('min_speed', 0) or speed > check.get('max_speed', math.inf):
            errors.append(f"{check['id']} edge {i}->{j}: speed outside limits")
    pairs = len(edges) if data.get('loop', True) and len(edges) > 1 else len(edges) - 1
    for i in range(pairs):
        j = (i + 1) % len(edges)
        acceleration = norm([b - a for a, b in zip(velocities[i], velocities[j])]) / ((dt[i] + dt[j]) / 2)
        edges[i]['acceleration_to_next_edge'] = acceleration
        if acceleration > check.get('max_acceleration', math.inf):
            errors.append(f"{check['id']} edges {i}->{j}: acceleration outside limit")
    return errors, edges


def binding(manifest, output, data):
    paths = [manifest, output] + [(manifest.parent / f['image']).resolve() for f in data['frames']]
    return [{'path': str(p), 'sha256': digest(p)} for p in paths]


def ppm(path):
    blob = Path(path).read_bytes()
    match = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', blob)
    if not match:
        raise ValueError('Unexpected FFmpeg RGB PPM header')
    w, h = map(int, match.groups())
    pixels = blob[match.end():]
    if len(pixels) != w * h * 3:
        raise ValueError('Unexpected RGB data length')
    return w, h, pixels


def region_mae(a, b, w, h, rect):
    x, y, rw, rh = rect
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = min(w, math.ceil((x + rw) * w)), min(h, math.ceil((y + rh) * h))
    total, count = 0, 0
    for row in range(y0, y1):
        start, end = (row * w + x0) * 3, (row * w + x1) * 3
        total += sum(abs(u - v) for u, v in zip(a[start:end], b[start:end]))
        count += end - start
    return total / count


def analyze(output, data, core, timeout=300, destination=None):
    ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
    ratio = min(1, 512 / max(data['width'], data['height']))
    w, h = max(1, round(data['width'] * ratio)), max(1, round(data['height'] * ratio))
    with tempfile.TemporaryDirectory(prefix='gif-review-') as temp:
        frames_dir = Path(temp) / 'png'
        frames_dir.mkdir()
        pattern = str(Path(temp) / 'frame-%06d.ppm')
        core.run([ffmpeg, '-v', 'error', '-ignore_loop', '1', '-i', str(output), '-vf', f'scale={w}:{h}',
                  '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', pattern], timeout)
        files = sorted(Path(temp).glob('*.ppm'))
        if len(files) != len(data['frames']):
            raise ValueError('Decoded frame count changed during inspection')
        core.run([ffmpeg, '-v', 'error', '-framerate', '100', '-i', pattern, '-frames:v', str(len(files)),
                  '-threads', '1', str(frames_dir / 'frame-%06d.png')], timeout)
        anchor = ppm(files[0])[2]
        pixel_hashes, regions = [], []
        for i, p in enumerate(files):
            _, _, pixels = ppm(p)
            pixel_hashes.append(hashlib.sha256(pixels).hexdigest())
            for region in data['plan'].get('fixed_regions', []):
                value = region_mae(anchor, pixels, w, h, region['rect'])
                regions.append({'id': region['id'], 'frame': i, 'mae': value,
                                'max_mae': region['max_mae'], 'violation': value > region['max_mae']})
        snapshot_hashes = [digest(p) for p in sorted(frames_dir.glob('*.png'))]
        if destination is not None:
            for p in frames_dir.glob('*.png'):
                shutil.copyfile(p, destination / p.name)
    duplicate_edges = []
    for i in range(len(pixel_hashes) if data.get('loop', True) and len(pixel_hashes) > 1 else len(pixel_hashes) - 1):
        j = (i + 1) % len(pixel_hashes)
        if pixel_hashes[i] == pixel_hashes[j]:
            duplicate_edges.append([i, j])
    automated = {'fixed_regions': regions, 'duplicate_edges': duplicate_edges,
                 'all_frames_identical': len(set(pixel_hashes)) == 1,
                 'snapshot_hashes': snapshot_hashes, 'analysis_size': [w, h], 'output_bytes': output.stat().st_size,
                 'note': 'Fixed-region MAE uses decoded GIF RGB downscaled to <=512px; not a natural-motion score'}
    return automated


def inspect(manifest, output, destination, core, timeout=300):
    manifest, output, destination = map(lambda p: Path(p).resolve(), (manifest, output, destination))
    data = core.load_manifest(manifest)
    plan_check(data)
    ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
    technical = core.verify(output, data, ffmpeg, timeout)
    before = binding(manifest, output, data)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(output, destination / 'preview.gif')
    frames_dir = destination / 'frames'
    frames_dir.mkdir()
    automated = analyze(output, data, core, timeout, frames_dir)
    if before != binding(manifest, output, data) or digest(destination / 'preview.gif') != technical['sha256']:
        raise ValueError('Inputs changed during inspection; create a fresh review')
    (destination / 'analysis.json').write_text(json.dumps(automated, indent=2), encoding='utf-8')
    checks = ['source_sequence', 'timing_and_events', 'normal_speed_playback']
    if data.get('loop', True):
        checks.append('loop_join')
    if automated['duplicate_edges'] and data['plan']['intent'] == 'motion':
        checks.append('duplicate_holds')
    review = {'version': 1, 'manifest': str(manifest), 'output': str(output), 'binding': before,
              'checks': {key: {'status': 'pending', 'note': ''} for key in checks}, 'issues': [],
              'observations': {c['id']: {'values': [None] * len(data['frames']), 'evidence': ''}
                               for c in data['plan'].get('measurements', [])}}
    write_page(destination, data, automated)
    review['review_assets'] = [{'path': str(p.relative_to(destination)), 'sha256': digest(p)}
                              for p in [destination / 'preview.gif', destination / 'analysis.json',
                                        destination / 'index.html', *sorted(frames_dir.glob('*.png'))]]
    (destination / 'review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'review_dir': str(destination), 'page': str(destination / 'index.html'), 'status': 'pending',
            'technical_status': 'pass', 'delivery_status': 'preview'}


def review_status(directory, core):
    directory = Path(directory).resolve()
    r = json.loads((directory / 'review.json').read_text(encoding='utf-8-sig'))
    if r.get('version') != 1:
        raise ValueError('Unsupported review version')
    manifest, output = Path(r['manifest']), Path(r['output'])
    data = core.load_manifest(manifest)
    plan_check(data)
    if binding(manifest, output, data) != r.get('binding'):
        return {'status': 'stale', 'issues': ['Manifest, source images or output changed; inspect again']}
    assets = r.get('review_assets', [])
    required = {'preview.gif', 'analysis.json', 'index.html'} | {f'frames/frame-{i+1:06d}.png' for i in range(len(data['frames']))}
    if {a.get('path', '').replace('\\', '/') for a in assets} != required:
        raise ValueError('Incomplete review asset binding')
    for asset in assets:
        p = (directory / asset['path']).resolve()
        if not p.is_relative_to(directory) or not p.is_file() or digest(p) != asset['sha256']:
            return {'status': 'stale', 'issues': ['Review snapshots changed; inspect again']}
    analysis = analyze(output, data, core)
    recorded_analysis = json.loads((directory / 'analysis.json').read_text())
    if analysis != recorded_analysis or digest(directory / 'preview.gif') != digest(output):
        return {'status': 'stale', 'issues': ['Automatic diagnostics differ from actual GIF; inspect again']}
    for i, expected in enumerate(analysis['snapshot_hashes']):
        if digest(directory / 'frames' / f'frame-{i+1:06d}.png') != expected:
            return {'status': 'stale', 'issues': ['Displayed snapshots differ from actual GIF; inspect again']}
    with tempfile.TemporaryDirectory(prefix='gif-page-check-') as temp:
        write_page(Path(temp), data, analysis)
        if digest(Path(temp) / 'index.html') != digest(directory / 'index.html'):
            return {'status': 'stale', 'issues': ['Review page differs from the current plan and decoder; inspect again']}
    failed, pending = [], []
    if analysis['all_frames_identical'] and data['plan']['intent'] == 'motion':
        failed.append('Motion was planned, but every decoded frame is identical')
    failed.extend(f"Fixed region {x['id']} exceeds its MAE limit at frame {x['frame']}"
                  for x in analysis['fixed_regions'] if x['violation'])
    if analysis['output_bytes'] > data['plan'].get('max_bytes', math.inf):
        failed.append('Output exceeds planned max_bytes')
    required_checks = ['source_sequence', 'timing_and_events', 'normal_speed_playback']
    if data.get('loop', True):
        required_checks.append('loop_join')
    if analysis['duplicate_edges'] and data['plan']['intent'] == 'motion':
        required_checks.append('duplicate_holds')
    checks = r.get('checks', {})
    for name in required_checks:
        item = checks.get(name, {})
        state = item.get('status', 'pending')
        if state not in ('pending', 'pass', 'revise'):
            raise ValueError(f'Invalid review status: {name}')
        if state == 'revise':
            failed.append(f'{name}: revision requested')
        elif state != 'pass' or not isinstance(item.get('note'), str) or not item['note'].strip():
            pending.append(f'{name}: missing acceptance evidence')
    issues = r.get('issues')
    if not isinstance(issues, list) or any(not isinstance(x, str) for x in issues):
        raise ValueError('issues must be a list of unresolved issue strings')
    failed.extend(x for x in issues if x.strip())
    metrics = {}
    for c in data['plan'].get('measurements', []):
        observed = r.get('observations', {}).get(c['id'], {})
        values = observed.get('values')
        if not isinstance(values, list) or len(values) != len(data['frames']):
            raise ValueError('Observation needs one value (or null) per displayed frame')
        if any(v is None for v in values):
            pending.append(c['id'] + ': measurements incomplete')
            continue
        violations, edges = measure(c, values, data)
        failed.extend(violations)
        metrics[c['id']] = edges
        if not isinstance(observed.get('evidence'), str) or not observed['evidence'].strip():
            pending.append(c['id'] + ': measurement evidence missing')
    return {'status': 'revise' if failed else 'pending' if pending else 'pass',
            'issues': failed, 'pending': pending, 'measurements': metrics,
            'output_sha256': digest(output), 'note': 'Acceptance relies on recorded human/agent observations; no automatic aesthetic judgment'}


def publish(directory, output, force, core, timeout=300):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    review_token = digest(directory / 'review.json')
    status = review_status(directory, core)
    if status['status'] != 'pass':
        raise ValueError(f"Cannot publish: review status is {status['status']}")
    r = json.loads((directory / 'review.json').read_text(encoding='utf-8-sig'))
    data = core.load_manifest(Path(r['manifest']))
    protected = [Path(item['path']) for item in r['binding']]
    if output.suffix.lower() != '.gif' or output.is_relative_to(directory) or output in protected:
        raise ValueError('Publish to a new .gif delivery path outside review and source assets')
    if output.exists() and (not force or any(os.path.samefile(output, p) for p in protected)):
        raise ValueError('Existing output is protected; --force only replaces unrelated delivery files')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.publish-gif-', dir=output.parent) as temp:
        candidate = Path(temp) / 'final.gif'
        shutil.copyfile(directory / 'preview.gif', candidate)
        report = core.verify(candidate, data, shutil.which('ffmpeg') or 'ffmpeg', timeout)
        if (report['sha256'] != status['output_sha256']
                or review_status(directory, core)['status'] != 'pass'
                or digest(directory / 'review.json') != review_token):
            raise ValueError('Review changed while preparing publication')
        if force:
            os.replace(candidate, output)
        else:
            os.link(candidate, output)
    return {**report, 'output': str(output), 'visual_status': 'recorded_pass', 'delivery_status': 'published'}


def write_page(directory, data, analysis):
    payload = {'frames': [{'src': f'frames/frame-{i+1:06d}.png', 'ms': f['duration_ms'], 'state': f['state']}
                          for i, f in enumerate(data['frames'])], 'loop': data.get('loop', True)}
    template = (Path(__file__).resolve().parents[1] / 'assets' / 'gif-review.html').read_text(encoding='utf-8')
    safe = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    replacements = {'DATA': safe, 'SUMMARY': html.escape(data['plan']['summary']),
                    'ANALYSIS': html.escape(json.dumps(analysis, ensure_ascii=False, indent=2))}
    template = re.sub(r'__(DATA|SUMMARY|ANALYSIS)__', lambda m: replacements[m.group(1)], template)
    (directory / 'index.html').write_text(template, encoding='utf-8')
