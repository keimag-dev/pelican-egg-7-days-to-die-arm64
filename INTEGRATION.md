# Real ARM64 integration verification

Verified on 2026-10-17 using **7 Days to Die V3.3.0(b18)**, official Linux depot294422 manifest `3031329678505041777`, native ARM64 DepotDownloader3.4.0, and the pinned Box64 ARM64 image in the Egg. This is an isolated real-game test, separate from CI fixtures.

## Results

| Gate | Observed result |
|---|---|
| Exported installer | Exact embedded script, real anonymous Steam validation/download, exit0 |
| Default runtime contract | Image's default CMD, Egg STARTUP, native Python PID1; game and supervisor UID/GID1000 |
| Readiness | Fresh `GameServer.Init successful` on first start, restart and post-reinstall start |
| Console | Real Docker STDIN → Python bridge → local game `gettime` response |
| Management isolation | Actual Linux TCP table: port8081 listening on127.0.0.1 only; no published management port |
| Save and normal stop | Set an intentional test clock, save acknowledgement, shutdown through STDIN, fresh cleanup/save markers and exit0 |
| Same-world restart | Same Navezgane save; saved main.ttw hash unchanged across load; clock `Day 2, 12:00` |
| SIGTERM | Separate Docker stop delivered to PID1, graceful game save and exit0; no forced kill/OOM |
| Stopped-game reinstall | Exact exported installer, real networked Steam validation of cached game files, exit0; intentionally stale helper refreshed |
| Persistent data | **76 files / 17,812,879 bytes**, root XML, all UserData and custom/Mods sentinels; SHA256 differences0 |
| Post-reinstall start | Fresh Ready, saved clock and console response, then normal save/stop exit0 |

The test used a normal private Docker bridge,4 CPUs and10GiB memory, no published ports, no privileged mode or host/Docker-socket mounts. Unrelated servers remained stopped and their selected configuration/world metadata hashes were unchanged.

## Compatibility regression discovered and fixed

The real V3.3 parser rejected the former unconditional `ControlPanelEnabled` XML injection. The helper no longer invents that legacy property; it disables it only when already present in an older configuration. The former XML `UserDataFolder` was also unsupported by the current enum and is now passed through the game's actual supported CLI argument. Three individual RED→GREEN regressions use shipped property names and source hashes, without redistributing game binaries. See README for handling an XML already modified by an earlier development helper.

## Exact tested payload

| File | SHA256 |
|---|---|
| `egg-7-days-to-die-arm64.json` | `dfc97acda30114da8f644145d8f79d1406bc1d575c6e0c2a1247e3999df92947` |
| embedded installation script / `install.sh` | `52bc93bd5e58f44f4b8ddca0b24f0aa1065a104bcd4ae459b38dfa088025c64d` |
| `runtime.py` | `18b9b4ff8a744aee960c0c8f4bd19cb6f86c8c588a1662cc94bd97dd011bfa58` |
| `installer.py` | `86a4b19d9220a415e55e28d8141027b3fe5f859b066060426722c091d53820d4` |

The final Egg includes the official red-7 icon. Image metadata does not alter the tested installation/runtime payload.

## Limits

- No client join, multiplayer load, long-duration soak, RWG generation or actual mod compatibility test for this distributable Egg. Sentinels prove preservation, not mod functionality.
- Docker payload lifecycle testing is not a full Panel/Wings server-provisioning/power/reinstall end-to-end test. Panel import is a separate publication check.
- Readiness can precede the first usable console response. A bounded QA-only read-only retry established real responses; this does not change the production startup marker.
- The game emits Telnet-disconnect IOException diagnostics; this is not a claim of warning-free logs.
- Reinstall was done with the game stopped, not without Internet. The official downloader validated cached depot files over the network.
- EAC and crossplay remain unsupported. Other branches and future builds are not covered by this verification.

Automated verification of the final source: Linux ARM64 **58/58 passed**; Windows **55 passed,3 platform skips**. Hosted CI separately exercises native Linux ARM64/x64 with Python3.11/3.13. Private raw evidence, worlds, binaries, credentials and host handles are not part of this repository.
