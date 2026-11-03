"""Build an offline wheel + synthetic demo handoff. No Git or private files needed.

Run with Python 3.10+, pip and setuptools>=68 already installed. The build is
offline; runtime users need only Python/pip and the generated wheel.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests' / 'fixtures' / 'synthetic'
SOURCE_MANIFEST = ROOT / 'examples' / 'synthetic-cases.json'
PATH_FIELDS = ('log', 'state', 'log_status', 'raw')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_demo(target, manifest_path=SOURCE_MANIFEST, fixture_dir=FIX):
    """Export only hash-verified synthetic inputs, with relocatable paths."""
    fixture_dir = fixture_dir.resolve()
    meta = json.loads((fixture_dir / 'provenance.json').read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for run in manifest['runs']:
        for key in PATH_FIELDS:
            if key not in run:
                continue
            source = (manifest_path.parent / run[key]).resolve()
            if source.parent != fixture_dir or source.name not in meta['files']:
                raise ValueError('handoff input must be a recorded synthetic fixture')
            run[key] = 'fixtures/' + source.name
    for name, expected in meta['files'].items():
        source = (fixture_dir / name).resolve()
        if source.parent != fixture_dir or sha(source) != expected:
            raise ValueError('synthetic provenance mismatch: ' + name)
    dest = target / 'fixtures'
    dest.mkdir(parents=True)
    for name in [*meta['files'], 'provenance.json']:
        shutil.copy2(fixture_dir / name, dest / name)
    manifest['description'] = ('Six hand-authored synthetic cases; no simulator was run. '
                               'Paths relative to this manifest; see fixtures/provenance.json.')
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def check_wheel(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        expected = {'simcheck/web/index.html', 'simcheck/web/app.js', 'simcheck/web/style.css',
                    'simcheck/__main__.py', 'simcheck/cli.py'}
        if not expected <= set(names):
            raise ValueError('wheel is missing runtime code/assets')
        for name in names:
            if not (name.startswith('simcheck/') or '.dist-info/' in name):
                raise ValueError('unexpected wheel member: ' + name)
        metadata = BytesParser().parsebytes(z.read(next(n for n in names if n.endswith('.dist-info/METADATA'))))
        if metadata.get_all('Requires-Dist'):
            raise ValueError('core wheel must have no third-party runtime dependencies')
        entry = z.read(next(n for n in names if n.endswith('.dist-info/entry_points.txt')))
        if b'simcheck = simcheck.cli:main' not in entry:
            raise ValueError('wheel is missing the simcheck command')
        return metadata['Version']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    # Build a frozen whitelist of application files. Runtime/private directories,
    # real logs and tests never become build inputs.
    with tempfile.TemporaryDirectory(prefix='simcheck-handoff-') as tmp:
        base = Path(tmp)
        source = base / 'source'
        inputs = [ROOT / 'pyproject.toml', ROOT / 'README.md',
                  *sorted((ROOT / 'simcheck').glob('*.py')),
                  *sorted((ROOT / 'simcheck' / 'web').glob('*.html')),
                  *sorted((ROOT / 'simcheck' / 'web').glob('*.js')),
                  *sorted((ROOT / 'simcheck' / 'web').glob('*.css'))]
        hashes = {}
        for path in inputs:
            relative = path.relative_to(ROOT)
            dest = source / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            hashes[relative.as_posix()] = sha(dest)
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-index',
                        '--no-build-isolation', '--wheel-dir', str(base / 'wheels'), str(source)], check=True)
        wheels = list((base / 'wheels').glob('*.whl'))
        if len(wheels) != 1:
            raise ValueError('expected exactly one application wheel')
        wheel = wheels[0]
        version = check_wheel(wheel)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        name = f'spectre-log-inspector-{version}-handoff-{stamp}'
        bundle = base / name
        bundle.mkdir()
        shutil.copy2(wheel, bundle / wheel.name)
        for src, dest in [('handoff.md', 'INSTALL.md'), ('agent-handoff.md', 'AGENT.md'),
                          ('schema.md', 'API.md')]:
            shutil.copy2(ROOT / 'docs' / src, bundle / dest)
        stage_demo(bundle / 'demo')
        template = {'quiet_after_s': 1800, 'watch': [{'name': 'SOA', 'code': 'CMI-275*'}],
                    'runs': [{'id': 'my-run', 'log': './runs/my-run/spectre.out'}]}
        (bundle / 'manifest.template.json').write_text(json.dumps(template, indent=2) + '\n', encoding='utf-8')
        build = {'version': version, 'created_utc': stamp, 'source_kind': 'working tree snapshot',
                 'source_sha256': hashes, 'demo': 'synthetic only; no simulator execution',
                 'publication': 'local artifact; not uploaded to a package index'}
        (bundle / 'BUILD.json').write_text(json.dumps(build, indent=2) + '\n', encoding='utf-8')
        files = sorted(p for p in bundle.rglob('*') if p.is_file())
        (bundle / 'FILES.sha256').write_text(''.join(f'{sha(p)}  {p.relative_to(bundle).as_posix()}\n'
                                                    for p in files), encoding='utf-8')
        output = args.out.resolve() / (name + '.zip')
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as z:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():
                    z.write(path, path.relative_to(base).as_posix())
        output.with_suffix('.zip.sha256').write_text(f'{sha(output)}  {output.name}\n', encoding='utf-8')
        print(output)


if __name__ == '__main__':
    main()
