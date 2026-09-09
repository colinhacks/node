#!/usr/bin/env python3
"""Fetch pinned published binaries as secondary, not same-source, controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def download(url, path):
    if os.name == 'nt':
        # Use Windows' TLS trust implementation, including intermediate-chain
        # retrieval, rather than Python's separately loaded certificate store.
        curl = Path(os.environ['SystemRoot']) / 'System32/curl.exe'
        if path.exists():
            raise FileExistsError(path)
        subprocess.run([str(curl), '--fail', '--location', '--silent',
                        '--show-error', '--connect-timeout', '20',
                        '--max-time', '300', '--output', str(path), url],
                       check=True, timeout=310)
        return
    with urllib.request.urlopen(url, timeout=120) as response, path.open('xb') as target:
        shutil.copyfileobj(response, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        parser.error('Pinned references require x64')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    windows = os.name == 'nt'
    suffix = '.exe' if windows else ''
    os_name = 'win' if windows else 'linux'
    if not windows and platform.system() != 'Linux':
        parser.error('Native Windows or Linux required')
    node_archive = f'node-v26.7.0-{os_name}-x64.' + ('zip' if windows else 'tar.xz')
    node_url = 'https://nodejs.org/dist/v26.7.0/' + node_archive
    checksums_url = 'https://nodejs.org/dist/v26.7.0/SHASUMS256.txt'
    download(checksums_url, root / 'SHASUMS256.txt')
    checksums = dict(line.split()[::-1] for line in
                     (root / 'SHASUMS256.txt').read_text().splitlines())
    bun_name = 'bun-windows-x64' if windows else 'bun-linux-x64'
    bun_expected = ('0a0620930b6675d7ba440e81f4e0e00d3cfbe096c4b140d3fff02205e9e18922'
                    if windows else '951ee2aee855f08595aeec6225226a298d3fea83a3dcd6465c09cbccdf7e848f')
    records = []
    inputs = [
        ('release-node', node_archive, node_url, checksums[node_archive],
         f'node-v26.7.0-{os_name}-x64/' + ('node.exe' if windows else 'bin/node'), 'v26.7.0'),
        ('bun', bun_name + '.zip',
         'https://github.com/oven-sh/bun/releases/download/bun-v1.3.14/' + bun_name + '.zip',
         bun_expected, bun_name + '/bun' + suffix, '1.3.14')]
    for label, name, url, expected, member, version in inputs:
        archive = root / name
        download(url, archive)
        assert sha256(archive) == expected, f'Checksum mismatch: {name}'
        binary = root / (label + suffix)
        if name.endswith('.zip'):
            with zipfile.ZipFile(archive) as package, package.open(member) as source, binary.open('xb') as target:
                shutil.copyfileobj(source, target)
        else:
            with tarfile.open(archive) as package, package.extractfile(member) as source, binary.open('xb') as target:
                shutil.copyfileobj(source, target)
        binary.chmod(0o755)
        environment = {k: v for k, v in os.environ.items()
                       if not k.upper().startswith(('NODE_', '__NUB_'))}
        result = subprocess.run([str(binary), '--version'], capture_output=True,
                                text=True, env=environment, timeout=30, check=True)
        assert result.stdout.strip() == version, result.stdout
        records.append(dict(label=label, url=url, archive_sha256=expected,
                            downloader='Windows system curl with TLS validation' if windows else 'Python urllib with TLS validation',
                            binary=str(binary), binary_sha256=sha256(binary),
                            version=result.stdout.strip(), stderr=result.stderr,
                            comparison='Published cross-version reference, not causal source control'))
        (root / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(records[-1]), flush=True)


if __name__ == '__main__':
    main()
