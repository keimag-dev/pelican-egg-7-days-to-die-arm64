"""Deterministic standalone PLCN_v3 export. Copyright (c) 2026 keimag-dev. MIT."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EGG_UUID = 'a2ea934e-37f4-41eb-93b5-49e060f033bd'  # Generated once for this standalone Egg; never regenerate per build.
RUNTIME_IMAGE = 'ghcr.io/pelican-eggs/yolks:box64@sha256:0354da2eed5021bfb09deb07d38e3a32192dd549e51e76158119f9cbc6d1d119'
UPDATE_URL = None  # Set only after a real public import URL exists.
INSTALLER_IMAGE = 'ghcr.io/parkervcp/installers@sha256:4087482f6b59d35fe468bb15b1ab88691c7446aa5ca06ab9eff2888a2f1373b1'


def installation_script():
    template = (ROOT / 'install.sh.in').read_text(encoding='utf-8')
    for name in ('installer', 'runtime'):
        source = (ROOT / (name + '.py')).read_text(encoding='utf-8')
        delimiter = '__PELICAN_' + name.upper() + '_PY__'
        if delimiter in source.splitlines() or not source.endswith('\n'):
            raise ValueError('Unsafe heredoc delimiter or missing final newline')
        template = template.replace('@@' + name.upper() + '_PY@@', source)
    return template


def make_egg(update_url=UPDATE_URL):
    variables = []
    def variable(key, name, default, description, rules, editable=True):
        variables.append({'sort': len(variables) + 1, 'name': name, 'description': description,
                          'env_variable': key, 'default_value': default,
                          'user_viewable': True, 'user_editable': editable, 'rules': rules})
    variable('STEAM_BRANCH', 'Steam branch', 'public', 'Install/reinstall selection. public is stable; latest_experimental may change format and is not a tested compatibility promise.', ['required', 'string', 'in:public,latest_experimental'])
    variable('STEAM_MANIFEST', 'Optional Linux depot manifest', '', 'Blank resolves current branch on install. Explicit positive uint64 decimal ID pins depot 294422; Steam can withdraw anonymous access. No silent fallback.', ['nullable', 'string', 'regex:/^[0-9]{1,20}$/'])
    variable('DEPOTDOWNLOADER_VERSION', 'DepotDownloader version', '3.4.0', 'Exact official SteamRE release x.y.z, Linux ARM64 standalone artifact; no Steam credentials.', ['required', 'string', r'regex:/^[0-9]+\.[0-9]+\.[0-9]+$/'])
    variable('DEPOTDOWNLOADER_SHA256', 'Optional tool SHA256', '', 'Optional operator-pinned SHA256 of the official ARM64 ZIP. Upstream digest is also verified whenever published. 3.4.0 upstream digest is absent.', ['nullable', 'string', 'regex:/^[a-fA-F0-9]{64}$/'])
    variable('INSTALL_TIMEOUT', 'Download timeout (seconds)', '3600', 'Installer-only timeout, 60..86400 seconds. Never limits the running game.', ['required', 'integer', 'min:60', 'max:86400'])
    variable('USER_XML_MODE', 'Configuration mode', 'managed', 'managed applies general variables at each boot. user preserves general XML/SandboxCode and ignores those variables. Console/Box64 safety settings are enforced in both modes. Persistent file: /home/container/serverconfig.xml.', ['required', 'string', 'in:managed,user'])
    variable('SERVER_NAME', 'Server name', '7 Days to Die ARM64', 'Managed ServerName; XML-escaped, not evaluated by a shell.', ['required', 'string', 'max:128'])
    variable('SERVER_DESCRIPTION', 'Description', '', 'Managed ServerDescription. No personally identifying defaults.', ['nullable', 'string', 'max:1024'])
    variable('SERVER_PASSWORD', 'Join password', '', 'Managed ServerPassword; blank permits passwordless joining. Set a password for restricted access. Panel admins can still view this environment variable.', ['nullable', 'string', 'max:128'])
    variable('SERVER_VISIBILITY', 'Server visibility', '0', '0 = not listed, 1 = friends, 2 = public. Not listed is NOT a firewall or authentication boundary.', ['required', 'string', 'in:0,1,2'])
    variable('MAX_PLAYERS', 'Maximum players', '8', 'Managed ServerMaxPlayerCount, 1..64. Not a measured ARM64 performance guarantee.', ['required', 'integer', 'min:1', 'max:64'])
    variable('GAME_WORLD', 'World source', 'Navezgane', 'Navezgane uses the shipped world (no heavy RWG on first boot). RWG generates a world and needs extra RAM/time. Custom imported worlds: select user XML mode.', ['required', 'string', 'in:Navezgane,RWG'])
    variable('GAME_NAME', 'Save game name', 'MyGame', 'Managed GameName. Changing this selects/creates a different save; it does not rename your existing world.', ['required', 'string', 'regex:/^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$/'])
    variable('WORLD_SEED', 'RWG seed', '7DTD', 'Managed WorldGenSeed; meaningful for new RWG generation, not an existing save.', ['required', 'string', 'max:128'])
    variable('WORLD_SIZE', 'RWG world size', '4096', 'Managed WorldGenSize. Ignored by shipped Navezgane. Larger RWG worlds are resource intensive.', ['required', 'string', 'in:4096,6144,8192,10240'])
    variable('SANDBOX_CODE', 'Optional sandbox code', '', 'Blank PRESERVES the shipped/current SandboxCode. V3.3 gameplay options use SandboxCode; legacy DayNightLength/BloodMoon properties are not reliable. Enter only a code exported by this exact game version; format validation cannot prove semantic compatibility.', ['nullable', 'string', 'max:4095', 'regex:/^(?:[A-Z]{3})+$/'])
    variable('SHUTDOWN_GRACE', 'Graceful shutdown seconds', '90', 'SIGINT/SIGTERM or Panel shutdown requests normal save/exit. Force termination only after 10..600 seconds. Set Wings stop timeout longer than this plus 5 seconds.', ['required', 'integer', 'min:10', 'max:600'])
    return {
        '_comment': 'Generated by build_egg.py; MIT covers helpers only, not the game or upstream tools.\n\n' + (ROOT / 'LICENSE').read_text(encoding='utf-8'),
        'meta': {'version': 'PLCN_v3', 'update_url': update_url},
        'name': '7 Days to Die ARM64 (Box64)',
        'icon': 'data:image/png;base64,' + base64.b64encode((ROOT / 'assets/7-days-to-die.png').read_bytes()).decode('ascii'),
        'author': '61485115+keimag-dev@users.noreply.github.com',
        'uuid': EGG_UUID,
        'description': 'Anonymous native ARM64 installation of Steam Linux dedicated app 294420/depot 294422, x86-64 game on Box64. Requires Linux ARM64, persistent writable volume and adjacent game allocations; never allocate management port 8081. No EAC/crossplay support. See bundled README before use.',
        'tags': ['7-days-to-die', 'arm64', 'box64'],
        'features': [],
        'docker_images': {'Box64 ARM64 (pinned)': RUNTIME_IMAGE},
        'file_denylist': [],
        'startup_commands': {'Default': 'exec python3 -u /home/container/.pelican/runtime.py'},
        'config': {'files': {}, 'startup': {'done': 'GameServer.Init successful'}, 'logs': {}, 'stop': 'shutdown'},
        'scripts': {'installation': {'script': installation_script(), 'container': INSTALLER_IMAGE, 'entrypoint': 'bash'}},
        'variables': variables,
    }


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Build the standalone PLCN_v3 Egg beside this script.')
    parser.add_argument('--update-url', default=UPDATE_URL, help='Explicit public Egg update URL (default: unset).')
    args = parser.parse_args()
    egg = make_egg(update_url=args.update_url)
    (ROOT / 'install.sh').write_text(egg['scripts']['installation']['script'], encoding='utf-8', newline='\n')
    target = ROOT / 'egg-7-days-to-die-arm64.json'
    target.write_text(json.dumps(egg, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print('Built ' + target.name)
