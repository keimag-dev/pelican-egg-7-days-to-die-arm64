# 7 Days to Die — Linux ARM64 / Box64 Pelican Egg

[![CI](https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/actions/workflows/ci.yml/badge.svg)](https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/actions/workflows/ci.yml)

**Pelican → Eggs → Import from URL:**

```text
https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/releases/latest/download/egg-7-days-to-die-arm64.json
```

Release assets include `SHA256SUMS`; the same stable URL is embedded as the Egg's update URL. Use a version-specific release URL when pinning. See [PUBLISHING.md](PUBLISHING.md) for guarded CI and release maintenance.

A standalone **PLCN_v3** Egg: anonymous **native ARM64 DepotDownloader** installs the official Linux x86-64 dedicated server, and **Box64** runs it. No SteamCMD, Box86, personal Steam account, private download host, remote controller or trial timer. Only the Egg/helpers are MIT licensed; the game, DepotDownloader, Box64 and images keep their upstream licenses and terms. No game binaries are redistributed.

## Import and prerequisites

Import `egg-7-days-to-die-arm64.json` in a current Pelican Panel. Its installer embeds the exact readable Python sources; this repository is not needed after import. The published JSON uses the stable release URL above as `meta.update_url`; the standalone builder defaults to null unless `--update-url` is supplied.

The standalone Egg has the newly generated, fixed UUID **`a2ea934e-37f4-41eb-93b5-49e060f033bd`**. Rebuilds and updates retain it so Pelican can identify a reimport as an update. It is an Egg identity, not a server/world UUID. **Forks intended as distinct Eggs must generate their own UUID once, set `EGG_UUID` in `build_egg.py`, and use their own update URL**; retaining this identity can cause an import to update the upstream Egg instead.

- **Linux ARM64 node**, compatible Box64 kernel/runtime, normal nonprivileged Wings server container; not x86-64, ARMv7, Windows, host networking or a privileged container.
- Runtime: `ghcr.io/pelican-eggs/yolks:box64@sha256:0354da2eed5021bfb09deb07d38e3a32192dd549e51e76158119f9cbc6d1d119` (verified image family: Box64 v0.4.5, native Python 3). Runs as the image's non-root `container` user.
- Installer: `ghcr.io/parkervcp/installers@sha256:4087482f6b59d35fe468bb15b1ab88691c7446aa5ca06ab9eff2888a2f1373b1`, `bash`, native ARM64/root. Python 3 and CA certificates are installed **only in the disposable installer** if absent. Do not substitute the non-root runtime image as an installer; Wings' `/mnt/install/install.sh` can be unreadable there.
- Plan **at least 30 GiB disk quota**, with additional headroom for worlds, mods and backups. A previously observed V3.3 install used roughly 15 GB; future releases may be larger. The installer's 2 GiB free-space preflight is only a last-resort safeguard, not a sizing guarantee.
- Start with **10–12 GiB RAM and 2–4 ARM cores** for a small Navezgane test, then measure. This is an initial budget, not a measured player-capacity promise. RWG/large worlds need more memory and time; don't run multiple large installers/tests concurrently on a constrained node.
- Set the **Wings stop timeout greater than `SHUTDOWN_GRACE + 5` seconds** (default grace 90, so at least 95, preferably 120 seconds). Otherwise Wings may kill a correctly saving game first.
- Default allocation becomes `SERVER_PORT` from Wings (no competing Egg variable). Reserve the base game port and the adjacent offsets used by the current game release; commonly TCP base and UDP base through base+3. Verify actual shipped listeners before publishing. This Egg never adds host/OCI/firewall/relay rules or allocations.
- **Never allocate/publish TCP 8081**, the bridge's fixed loopback Telnet port. No dashboard/control-panel allocation. Do not select a game port whose required adjacent range overlaps 8081.

Visibility 0 is **unlisted**, not private networking. The default join password is blank; set `SERVER_PASSWORD` and restrict networking yourself where access must be private. Panel administrators can view environment variables and files; log redaction is not a secret vault.

## Install/version selection

| Variable | Default | Effect |
|---|---|---|
| `STEAM_BRANCH` | `public` | `public` or `latest_experimental`, selected at install/reinstall |
| `STEAM_MANIFEST` | blank | Optional positive uint64 Linux depot manifest; blank resolves current branch |
| `DEPOTDOWNLOADER_VERSION` | `3.4.0` | Explicit official SteamRE `x.y.z` release, native `linux-arm64` ZIP |
| `DEPOTDOWNLOADER_SHA256` | blank | Optional operator pin of that ZIP; upstream SHA256 is also checked when published |
| `INSTALL_TIMEOUT` | `3600` | Installer-only timeout, 60–86400 seconds; never a game runtime limit |

The installer downloads **app 294420 / Linux depot 294422**, `-os linux -osarch 64`, anonymously with `-validate` and four concurrent chunk downloads. No account variables exist. Invalid values, missing releases, denied old manifests, bad hashes and unsuccessful downloads **fail** instead of switching versions. A manifest can be withdrawn from anonymous entitlement; no personal-account fallback is implemented.

During implementation, the official GitHub API reported **3.4.0 as latest**, with `DepotDownloader-linux-arm64.zip` size **32,026,406 bytes**, published 2025-05-09. Its API `digest` was null. A real HTTPS download produced SHA256:

```
d9fb612ccebc1db8eeea3b4045d2221ec70431381393ce908fb72f01d4f9c812
```

This is an **observed artifact hash**, not a publisher-signed checksum. Enter it as an operator pin if desired for 3.4.0. The installer records the actual artifact hash/source, requested branch/manifest and upstream digest in `.pelican/installation.json`; DepotDownloader also retains its depot metadata beneath `game/.DepotDownloader`. No static game manifest or old trial build is forced.

Core dumps are disabled. **Do not apply `RLIMIT_FSIZE` / `ulimit -f` to native .NET DepotDownloader**: .NET's virtual memfd allocations can fail independently of real disk usage. Tool downloads have declared-size/hash/extraction budgets; game downloads have the selected install timeout. Operator disk/memory quotas remain necessary.

## Persistence and configuration

Volume layout:

```
/home/container/
  serverconfig.xml          # persistent active config (includes secrets)
  UserData/                 # persistent saves/admin data
  game/                     # official depot files, including stock serverconfig.xml
    Mods/                   # custom mods go here; preserve your own backups
  .pelican/
    installer.py
    runtime.py
    installation.json
```

First install copies the **actual shipped** `game/serverconfig.xml` only if the persistent root file is absent. The source is opened first, copied into a same-filesystem temporary file, flushed/fsynced and XML-validated before atomic **create-only** publication. A failed copy/validation leaves no empty or partial root XML; a user file created before publication wins without being overwritten. Reinstall updates official game files in `game/`; it does not reset root XML, UserData, world/admin settings or unrelated custom files. No directory is wiped. Official tracked files can change on upgrade: don't place custom modifications on top of depot-owned files without backups. Back up the stopped volume before changing branch/manifest; older builds may not read newer saves. Reinstall is **not transactional rollback** of game binaries if the download fails.

The root bootstrap rejects symlink/non-regular helper destinations, publishes helpers with explicit single-entry `mv -fT` semantics, and executes only the private staged installer with Python isolated imports (`-I`), never the user-writable published installer path. Installation/reinstallation still requires a stopped volume; this is not a general defense against concurrent hostile volume mutation.

At each boot, root XML is parsed with comments preserved and written by a flushed/fsynced **atomic replacement**. DTD/entities, duplicate properties, malformed XML, unsafe names, controls and out-of-range managed values fail without replacing the original. Strings are XML escaped and never interpolated into shell commands.

`USER_XML_MODE` is a dropdown:

- **`managed` (default)** updates only `SERVER_NAME`, `SERVER_DESCRIPTION`, `SERVER_PASSWORD`, Wings `SERVER_PORT`, `SERVER_VISIBILITY`, `MAX_PLAYERS`, `GAME_WORLD`, `GAME_NAME`, `WORLD_SEED`, `WORLD_SIZE`, plus a nonblank `SANDBOX_CODE`. Unknown properties and a blank-override SandboxCode are preserved.
- **`user`** ignores those general variables and preserves your manually edited XML/SandboxCode. The same management/Box64 safety settings below are still mandatory. This is an opt-out from general config management, **not** from the secure console contract.

Defaults: Navezgane, save `MyGame`, 8 player slots, unlisted. Navezgane is shipped and avoids first-boot RWG. `GAME_WORLD=RWG` and `WORLD_SIZE` 4096/6144/8192/10240 are available, but a different seed/name/size selects or creates a different world rather than migrating your save. Use user mode for custom imported world names.

**V3.3 uses SandboxCode for gameplay options.** Legacy `DayNightLength`, `BloodMoonFrequency` and `GameDifficulty` properties/getgamepref can show stored defaults rather than effective sandbox values. No daily-horde, faster-day, low-entity, god/admin or other trial settings are applied. `SANDBOX_CODE` blank preserves your shipped/current code. A custom value must be exported for the exact installed game version; uppercase triplet format checking cannot prove option IDs are semantically supported. Use `getsandboxoptions` without arguments to inspect current effective options; `getsandboxoptions true` has different behavior on the observed V3.3 build. No hardcoded preset IDs or invented difficulty mapping are shipped. The normal **20 FPS target is not changed**.

In both modes the bridge enforces: `TelnetEnabled=true`, `TelnetPort=8081`, `TelnetPassword` empty, web dashboard/terminal window disabled, EAC and crossplay disabled. An existing legacy `ControlPanelEnabled` property is disabled, but **never added**: the actual V3.3.0(b18) parser rejects it. Persistent data is selected with the game's supported **CLI** argument `-UserDataFolder=/home/container/UserData`, not an XML property (V3.3's enum contains only `UNUSED_UserDataFolder`). The regression fixture records actual shipped property names and stock XML/DLL hashes; no game binary is distributed. Empty Telnet password is the observed V3.3 loopback-binding convention; the bridge additionally reads **actual Linux `/proc/net/tcp{,6}` listeners** and stops on a non-loopback management listener. Do not use host networking or publish management ports. EAC-protected clients and crossplay are **unsupported**, not silently promised.

If an earlier helper has already added `ControlPanelEnabled` or `UserDataFolder` to a **V3.3** root XML, stop the server, back up the root XML, then remove those two obsolete XML properties before starting this helper. Reinstall deliberately preserves root XML and will not silently erase custom settings. Do not remove a valid legacy control-panel property from an older game schema merely on the basis of this V3.3 finding.

## Console and stop lifecycle

Startup is fixed: `python3 -u /home/container/.pelican/runtime.py`; users cannot inject shell fragments. The helper launches `box64 .../7DaysToDieServer.x86_64 -quit -batchmode -nographics -dedicated`, with the persistent absolute config and game log directed to `/dev/stdout`. Readiness follows the game's `GameServer.Init successful` marker, not process existence.

- Game stdout and console responses are filtered before Panel output. Preference passwords, auth variants (including `AuthSteam`, `Auth_Steam`, EOS), tokens, obvious platform identities and known XML passwords are redacted. No raw local game-log copy is created by the bridge; Panel/Wings log retention is an operator setting.
- Enter commands in the Pelican console. After readiness they are sent over **127.0.0.1:8081**, and the bridge reads response bytes **before closing**. Not-ready commands are rejected, not replayed later.
- Telnet has no reliable command completion framing: each exchange uses a 3-second absolute deadline, 0.5-second post-response idle interval and 64 KiB byte budget. Long commands may continue writing to game stdout. A send/no-response is explicitly not reported as successful execution. Game-side Telnet disconnect diagnostics may still occur with some builds.
- Use normal Panel **Stop** (`shutdown`) so Wings expects the game to exit. SIGINT/SIGTERM also request `shutdown` and allow the configured 90-second save grace, then terminate/kill if necessary. Normal child exit 0 remains 0; crashes and forced stops are nonzero. Changing global Wings crash recovery is not required.
- A detected non-loopback management listener is a **security failure**, not a normal Stop: the bridge immediately SIGKILLs the Linux child process group and exits nonzero, without waiting for `SHUTDOWN_GRACE` or a console acknowledgement. This can lose unsaved state; reducing exposure takes precedence over save grace. Descendants that deliberately escape the process group are outside this supervisor's boundary.
- stdin EOF merely closes the input reader; **it does not stop the game**. There is no 20-minute/default runtime deadline and no log-size-triggered game kill. Console queue depth 64, 4096-character commands and 8192-byte log-line chunks bound helper buffers. Oversized log lines are dropped, never used to stop the child.

## Build and verify

Python 3.10+ stdlib only on the build machine:

```sh
python -W error -m unittest discover -s tests -v
python build_egg.py --update-url https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/releases/latest/download/egg-7-days-to-die-arm64.json
python -W error scripts/publication_guard.py --verify-build
bash -n install.sh
```

`build_egg.py` deterministically generates `install.sh` and `egg-7-days-to-die-arm64.json` from `install.sh.in`, `installer.py`, `runtime.py`. Both files are always written beside the builder, even when it is invoked from another working directory. For a release, run `python build_egg.py --update-url PUBLIC_EGG_JSON_URL` **after tests**, replacing the placeholder with the real public JSON download URL; the override does not change `UPDATE_URL = None` or the fixed Egg UUID. The CLI regression builds only in its own temporary module, never overwriting release artifacts with a null-URL copy. The JSON contains the same complete installer script. Never edit generated files as the source of truth. See [TESTING.md](TESTING.md) for actual TDD evidence and the separate real ARM64 integration gates. Local socket/child fixtures are **not** a claim that a real game install, client join, mods, restart/reinstall persistence or long soak has passed; those require the parent/operator's isolated tests.
