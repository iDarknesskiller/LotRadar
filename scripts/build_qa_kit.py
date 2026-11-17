#!/usr/bin/env python3
"""Build the PRIVATE, self-contained Windows QA test kit (Windows 11 / R3 installer tests).

    python scripts/build_qa_kit.py [--out-dir DIR]

* Requires a clean working tree; every kit file comes from blobs committed at HEAD (never the working tree).
* Builds a DEVELOPMENT installer (no --asset-dir, so no private branding) with scripts/build_installer.py,
  verifies it, checks its manifest names HEAD, and refuses if any private branding file is inside.
* Output: LotRadar-Win11-R3-QA-<shortsha>.zip (deterministic). Never commit or publish the kit: it is
  delivered privately with its SHA-256.
"""
import argparse, glob, hashlib, io, json, os, subprocess, sys, tempfile, time, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE_NAMES = ('business_card.png', 'dedication.jpg', 'lotradar_logo.png', 'lotradar.ico')
KIT_FILES = [  # (committed source path, path inside the kit)
    ('tests/windows/qa-kit/START_HERE.txt', 'START_HERE.txt'),
    ('tests/windows/qa-kit/RUN_WINDOWS11_TESTS.cmd', 'RUN_WINDOWS11_TESTS.cmd'),
    ('tests/windows/qa-kit/RUN_FULL_LAUNCH_TESTS.cmd', 'RUN_FULL_LAUNCH_TESTS.cmd'),
    ('tests/windows/qa-kit/RUN_ONEDRIVE_TESTS.cmd', 'RUN_ONEDRIVE_TESTS.cmd'),
    ('tests/windows/qa-kit/RUN_CLEANUP_SAFETY_TESTS.cmd', 'RUN_CLEANUP_SAFETY_TESTS.cmd'),
    ('tests/windows/qa-kit/Run-QAKit.ps1', 'tools/Run-QAKit.ps1'),
    ('tests/windows/qa-kit/LotRadarQA.OneDrive.ps1', 'tools/LotRadarQA.OneDrive.ps1'),
    ('tests/windows/qa-kit/LotRadarQA.Cleanup.ps1', 'tools/LotRadarQA.Cleanup.ps1'),
    ('tests/windows/qa-kit/LotRadarQA.CleanupSelfTest.ps1', 'tools/LotRadarQA.CleanupSelfTest.ps1'),
    ('tests/windows/Test-LotRadarInstaller.ps1', 'tools/Test-LotRadarInstaller.ps1'),
]


def git(*args):
    return subprocess.run(['git', '-C', ROOT] + list(args), check=True, capture_output=True).stdout


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def crlf(data):
    return data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')


def fail(msg):
    print('ERROR: ' + msg, file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out-dir', default=os.path.join(ROOT, 'dist'))
    a = ap.parse_args()
    if git('status', '--porcelain').strip():
        fail('working tree is not clean; commit first so the kit matches a commit')
    head = git('rev-parse', 'HEAD').decode().strip()
    epoch = int(git('show', '-s', '--format=%ct', 'HEAD').decode().strip())
    stamp = time.gmtime(epoch)[:6]

    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'build_installer.py'), 'build',
                            '--mode', 'development', '--out-dir', tmp], capture_output=True, text=True)
        if r.returncode:
            fail('installer build failed:\n' + r.stdout + r.stderr)
        zips = glob.glob(os.path.join(tmp, 'LotRadar-Installer-*.zip'))
        if len(zips) != 1:
            fail('expected exactly one installer zip, found %d' % len(zips))
        pkg_path = zips[0]
        v = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'build_installer.py'), 'verify', pkg_path],
                           capture_output=True, text=True)
        if v.returncode:
            fail('installer verify failed:\n' + v.stdout + v.stderr)
        pkg = open(pkg_path, 'rb').read()
        pkg_name = os.path.basename(pkg_path)

    with zipfile.ZipFile(io.BytesIO(pkg)) as z:
        manifest = json.loads(z.read('Install-Manifest.json'))
        private = [n for n in z.namelist() if n.lower().rsplit('/', 1)[-1] in PRIVATE_NAMES]
    if private:
        fail('private branding found in the development package: %s' % private)
    if manifest.get('source_commit') != head:
        fail('package commit %s != HEAD %s' % (manifest.get('source_commit'), head))
    if manifest.get('build_type') != 'development':
        fail('expected a development build, got %r' % manifest.get('build_type'))
    if not any(p['path'] == 'requirements.txt' for p in manifest['payload_files']):
        fail('requirements.txt missing from the payload (R3 needs it)')

    kit_name = 'LotRadar-Win11-R3-QA-' + head[:7]
    files = {}
    for src, dst in KIT_FILES:
        data = git('show', 'HEAD:' + src)
        if dst == 'START_HERE.txt':
            data = (data.decode('utf-8').replace('{{COMMIT}}', head).replace('{{PACKAGE_FILE}}', pkg_name)
                    .replace('{{PACKAGE_SHA256}}', sha256(pkg))).encode('utf-8')
        try:
            data.decode('ascii')
        except UnicodeDecodeError:
            fail(dst + ' is not plain ASCII (Windows PowerShell 5.1 / cmd.exe would misread it)')
        files[dst] = crlf(data)
    files['package/' + pkg_name] = pkg
    info = {'kit': kit_name, 'source_commit': head, 'build_type': manifest['build_type'],
            'package_version': manifest.get('package_version'), 'package_file': pkg_name,
            'package_sha256': sha256(pkg), 'payload_files': len(manifest['payload_files']),
            'note': 'TEST KIT ONLY. Development installer without private branding. Not a release.'}
    files['KIT_INFO.json'] = (json.dumps(info, indent=2, sort_keys=True) + '\r\n').encode('ascii')
    files['KIT_SHA256SUMS.txt'] = ''.join('%s  %s\r\n' % (sha256(files[k]), k) for k in sorted(files)).encode('ascii')

    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, kit_name + '.zip')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(files):
            zi = zipfile.ZipInfo(kit_name + '/' + name, date_time=stamp)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, files[name])
    with open(out, 'wb') as f:
        f.write(buf.getvalue())
    print('kit            : ' + out)
    print('kit sha256     : ' + sha256(buf.getvalue()))
    print('source_commit  : ' + head)
    print('package        : %s (%s) sha256 %s' % (pkg_name, manifest['build_type'], sha256(pkg)))
    print('files          : %d' % len(files))


if __name__ == '__main__':
    main()
