"""Anonymous native ARM64 installer. Copyright (c) 2026 keimag-dev. MIT."""
import re


def validate(env):
    branch = env.get('STEAM_BRANCH', 'public')
    manifest = env.get('STEAM_MANIFEST', '')
    version = env.get('DEPOTDOWNLOADER_VERSION', '3.4.0')
    checksum = env.get('DEPOTDOWNLOADER_SHA256', '')
    timeout = env.get('INSTALL_TIMEOUT', '3600')
    if branch not in ('public', 'latest_experimental'):
        raise ValueError('STEAM_BRANCH must be public or latest_experimental')
    if manifest and (not re.fullmatch(r'[0-9]{1,20}', manifest) or not 0 < int(manifest) < 2**64):
        raise ValueError('STEAM_MANIFEST must be a positive uint64 decimal ID')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('DEPOTDOWNLOADER_VERSION must be an explicit x.y.z version')
    if checksum and not re.fullmatch(r'[a-fA-F0-9]{64}', checksum):
        raise ValueError('DEPOTDOWNLOADER_SHA256 must be a 64-digit SHA256')
    if not re.fullmatch(r'[0-9]{1,6}', timeout) or not 60 <= int(timeout) <= 86400:
        raise ValueError('INSTALL_TIMEOUT must be 60..86400 seconds (installer only)')
    return branch, manifest, version, checksum.lower(), int(timeout)


import os
from pathlib import Path
import shutil
import stat


def release_asset(release, version):
    """Only trust the exact ARM64 asset on the requested official release."""
    if release.get('tag_name') != 'DepotDownloader_' + version or release.get('draft'):
        raise ValueError('Release tag mismatch or draft')
    matches = [a for a in release.get('assets', []) if a.get('name') == 'DepotDownloader-linux-arm64.zip']
    if len(matches) != 1:
        raise ValueError('Expected exactly one Linux ARM64 release asset')
    asset = matches[0]
    expected = f'https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_{version}/DepotDownloader-linux-arm64.zip'
    if asset.get('browser_download_url') != expected or not 0 < asset.get('size', 0) <= 128 * 1024 * 1024:
        raise ValueError('Unexpected official asset URL or size')
    digest = asset.get('digest')
    if digest and not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
        raise ValueError('Unsupported upstream artifact digest')
    return asset


def extract_tool(archive, destination):
    from pathlib import PurePosixPath
    entries = archive.infolist()
    if len(entries) > 1000 or sum(i.file_size for i in entries) > 256 * 1024 * 1024:
        raise ValueError('Tool archive exceeds extraction budget')
    names = set()
    for info in entries:
        name = info.filename
        path = PurePosixPath(name)
        if (not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts
                or stat.S_ISLNK(info.external_attr >> 16) or name in names):
            raise ValueError('Unsafe archive entry')
        names.add(name)
    archive.extractall(destination)
    tool = destination / 'DepotDownloader'
    if not tool.is_file() or tool.is_symlink():
        raise ValueError('Missing native DepotDownloader executable')
    tool.chmod(0o755)
    return tool


def finalize_install(root):
    """Only downloaded game files update; persistent XML/UserData are never reset."""
    root = Path(root)
    binary = root / 'game' / '7DaysToDieServer.x86_64'
    if binary.is_symlink():
        raise ValueError('Game executable cannot be a symlink')
    with binary.open('rb') as f:
        header = f.read(20)
    if header[:4] != b'\x7fELF' or header[18:20] != b'\x3e\x00':
        raise ValueError('Expected x86-64 Linux game executable')
    binary.chmod(0o755)
    persistent = root / 'serverconfig.xml'
    if persistent.is_symlink():
        raise ValueError('Persistent config cannot be a symlink')
    if not persistent.exists():
        stock = root / 'game' / 'serverconfig.xml'
        if stock.is_symlink():
            raise ValueError('Stock config cannot be a symlink')
        temporary = None
        try:
            # Open the source first; errors never create a partial persistent file.
            with stock.open('rb') as src, tempfile.NamedTemporaryFile(dir=root, prefix='.serverconfig-', delete=False) as out:
                temporary = Path(out.name)
                shutil.copyfileobj(src, out)
                out.flush()
                os.fsync(out.fileno())
            import xml.etree.ElementTree as ET
            data = temporary.read_bytes()
            if len(data) > 4 * 1024 * 1024 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper() or b'\x00' in data:
                raise ValueError('Unsafe stock config XML or size')
            try:
                settings = ET.fromstring(data)
            except ET.ParseError as exc:
                raise ValueError('Invalid stock config XML') from exc
            if settings.tag != 'ServerSettings':
                raise ValueError('Stock config has an unexpected XML root')
            names = [node.get('name') for node in settings.findall('property')]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate stock XML property names')
            temporary.chmod(0o600)
            try:
                # Atomic create-only publish; a concurrently added user config wins.
                os.link(temporary, persistent)
            except FileExistsError:
                pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def download_command(tool, game_dir, env):
    branch, manifest, _, _, _ = validate(env)
    command = [str(tool), '-app', '294420', '-depot', '294422', '-os', 'linux', '-osarch', '64',
               '-branch', branch, '-dir', str(game_dir), '-validate', '-max-downloads', '4']
    if manifest:
        command += ['-manifest', manifest]
    return command


import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone


def install(root, env):
    branch, manifest, version, expected_hash, timeout = validate(env)
    if sys.platform != 'linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise ValueError('Installer requires native Linux ARM64')
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # NOT RLIMIT_FSIZE (.NET memfd).
    root = Path(root)
    metadata_dir = root / '.pelican'
    game_dir = root / 'game'
    for path in (root, metadata_dir, game_dir):
        if path.is_symlink():
            raise ValueError('Install directories cannot be symlinks')
        path.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 2 * 1024**3:
        raise ValueError('Less than 2 GiB physical disk free; game needs substantially more')
    url = f'https://api.github.com/repos/SteamRE/DepotDownloader/releases/tags/DepotDownloader_{version}'
    headers = {'User-Agent': 'pelican-community-eggs-7dtd-arm64', 'Accept': 'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('Release metadata exceeds budget')
    asset = release_asset(json.loads(payload), version)
    with tempfile.TemporaryDirectory(prefix='install-', dir=metadata_dir) as temporary:
        directory = Path(temporary)
        archive_path = directory / 'depotdownloader.zip'
        sha = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': headers['User-Agent']}), timeout=30) as response, archive_path.open('xb') as out:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > asset['size']:
                    raise ValueError('Downloaded tool exceeds declared size')
                sha.update(block)
                out.write(block)
        actual_hash = sha.hexdigest()
        if total != asset['size']:
            raise ValueError('Truncated tool archive')
        upstream_hash = (asset.get('digest') or '').removeprefix('sha256:').lower()
        if (expected_hash and actual_hash != expected_hash) or (upstream_hash and actual_hash != upstream_hash):
            raise ValueError('DepotDownloader SHA256 mismatch')
        with zipfile.ZipFile(archive_path) as archive:
            tool = extract_tool(archive, directory)
        native_env = os.environ.copy()
        native_env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '1'
        subprocess.run(download_command(tool, game_dir, env), check=True, timeout=timeout, env=native_env)
        finalize_install(root)
        provenance = {
            'installed_at': datetime.now(timezone.utc).isoformat(),
            'app_id': 294420, 'depot_id': 294422, 'branch': branch,
            'requested_manifest': manifest or None,
            'depotdownloader_version': version, 'artifact_url': asset['browser_download_url'],
            'artifact_sha256': actual_hash, 'upstream_digest': asset.get('digest'),
            'operator_digest_verified': bool(expected_hash),
            'note': 'Resolved depot manifest is recorded by DepotDownloader in game/.DepotDownloader; no version fallback.',
        }
        saved = directory / 'installation.json'
        saved.write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
        os.replace(saved, metadata_dir / 'installation.json')
    print('Anonymous Linux depot installed; persistent config and UserData preserved.', flush=True)


if __name__ == '__main__':
    try:
        install(Path('/mnt/server'), os.environ)
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print('Installation failed: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
