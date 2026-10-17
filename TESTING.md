# Verification and TDD evidence

## Final standalone ARM64 verification

The final icon-inclusive source passes **58/58 tests on native Linux ARM64** and **55 passed / 3 platform skips on Windows**. Real V3.3.0(b18) boot, STDIN console, save/normal stop, same-world restart, SIGTERM and stopped-game reinstall preservation/post-reinstall boot all passed. See [INTEGRATION.md](INTEGRATION.md) for exact payload hashes, the discovered configuration compatibility fixes and explicit limitations. Older implementation notes below are retained as provenance, not the current live-QA status.

## Local result

On the implementation host, **Windows / Python 3.14.7**, the final executed command was:

```sh
python build_egg.py
python -W error -m unittest discover -s tests -v
bash -n install.sh
```

Result: **43 tests discovered: 40 passed, 3 explicitly skipped**, no warnings; generated shell syntax passed. Explicit `compile(...)` checks also passed for **11 Python files**. The skips are the two native-symlink destination cases (this Windows account lacks symlink privilege) and the Linux `/proc/net`/process-group descendant regression. These are integration gates, not claimed successes. No package installation is needed for local tests. `test_generated_files_match_sources` verifies both default-build generated files exactly match the current builder and source helpers.

The tests use actual temporary XML/files, real IPv4 loopback sockets and real native child processes, not mocked success responses. `tests/fake_game.py` is explicitly a tiny socket/process fixture, **not** the game. The signal test delivers Python's real `SIGTERM` handler with `signal.raise_signal`, then observes the real child socket acknowledgement and exit 0. This does not claim an OS `docker stop` signal or real 7DTD save was tested on Windows.

## Observed incremental RED → GREEN slices

These were executed as separate tests/implementation increments, not tests appended only at completion:

| Slice | Observed RED | Subsequent GREEN |
|---|---|---|
| Managed XML merge | `managed XML configurator is not implemented` | Original comments/custom values/SandboxCode preserved, escaped XML roundtrip |
| Validation / user mode | Missing ValueError for port 0; unsafe DTD accepted, bad XML unnormalized | 3 config tests passed after strict validation, duplicate/root/DTD handling and user-mode opt-out |
| Console exchange / redaction | `console bridge is not implemented`, `log redaction missing` | Real delayed socket response received before disconnect, single-line bounds and secret suppression |
| Child supervision | `production supervisor is missing` in three lifecycle tests | Real EOF-tolerant child exit 7, real shutdown socket/save acknowledgement exit 0, uncooperative-child forced nonzero exit |
| Native anonymous installer args | `native installer missing` | Exact fixed app/depot/platform argv, branch/manifest selection, literal malformed values rejected |
| Archive / config preservation | Missing asset verifier and persistent finalizer | Fixed official release URL, traversal rejection, native tool extraction, root XML/world preservation across two finalizations |
| Actual management binding / launch | Missing binding probe and game launch contract | `/proc/net` fixtures reject wildcard/nonloopback, fixed game argv leaves target FPS unchanged |
| Entrypoints | Missing installer/runtime entrypoints | Invalid installer selection/grace rejected before touching state or spawning |
| Native standalone export | `standalone Egg builder is missing` | PLCN_v3 objects, startup mapping, dropdown rules, exact readable embedded sources |
| Auth variants | Two real assertion failures for `AuthSteam` and `AuthEOS` | Both compact and underscored variants suppressed |
| Short secret / readiness | A password `a` changed the ready marker to `G[REDACTED]meServer...` | Recognized real marker emits a separate static safe status line |
| Actual shipped readiness prefix | Captured V3.3 `INF [Steamworks.NET] GameServer.Init successful` was missed by an over-narrow pattern | Added the real shipped prefix and exercised it through the socket fixture |
| Publication hook / snapshots | Missing update_url override; stale generated helper failed exact-source comparison | Explicit publication override/one `UPDATE_URL` constant; rebuilt exact snapshots |

A missing `return command` was also caught immediately by the existing exact-argv regression test while extending the installer, fixed, then all tests rerun. A Python invalid-escape SyntaxWarning in a Laravel regex was corrected to a raw string; final `-W error` execution was clean.

Additional real-process coverage passes for stdin `gettime` roundtrip after readiness, oversized output (100,000 bytes) not stopping the child, literal-secret filtering, stdin EOF not triggering shutdown, child exit propagation and bounded grace termination. These are short functional tests, not a 20-minute real-time soak.

## Pre-publication review fixes

The handoff already contained the basic R1 directory-destination/staged-execution fix and the R2 temporary/create-only-copy fix, plus a first R3 short SIGTERM escalation. Their inherited regressions passed before this follow-up; they were not misrepresented as new failing tests. This follow-up executed these additional incremental RED → GREEN slices:

| Slice | Observed RED before production change | GREEN |
|---|---|---|
| R1 import isolation | A real Bash bootstrap with user-controlled `PYTHONPATH` imported the fixture `decimal.py`, exiting 91 | `python3 -I` executes only trusted staged code and stdlib imports; regular-helper exact publication and replacement of the persistent helper immediately before execution cannot redirect that execution |
| R2 validate before publication | DTD/entity and duplicate-property stock XML were published; malformed XML escaped as an unnormalized parser exception | Invalid stock XML raises `ValueError`, staging is removed, and persistent XML remains absent |
| R3 kill the security-failing group | The real-child signal adapter observed SIGTERM only; exiting the leader could skip killing a listener-holding descendant | Security violations send immediate SIGKILL to the Linux group, independent of normal save grace, and return nonzero |
| Publication CLI | A real subprocess `--update-url` build ignored its URL and emitted null | Both exact artifacts are written beside the builder, including when invoked from another directory; subprocess tests use temporary copies only |
| Standalone identity | Existing derived UUID parsed as version 5 instead of the required newly generated fixed version 4 | Newly generated UUIDv4 is valid and stable across repeated builds and URL overrides |

Additional real-file checks cover missing-source recovery, interrupted copy, fsync failure, complete fsynced staging before create-only publication, a concurrently added user XML winning without clobber, existing XML/world preservation, and temporary-file cleanup. Only I/O faults/race timing are injected; filesystem changes are real.

The unsafe-socket regression starts a real child bound to IPv4 wildcard, deliberately ignores console shutdown, uses the **default 90-second grace**, and requires a nonzero security exit plus a closed listener in under three seconds (six-second outer timeout). On Windows only the unavailable `/proc/net` probe is adapted using the child's real `getsockname` and a live TCP connection. A separate Linux-only case starts a listener-holding SIGTERM-ignoring descendant in the child's real process group; it is **not run on this Windows host**. The portable signal adapter verifies the production group-signal choice with a real child, not Linux kernel group semantics. Linux CI/integration must run the skipped native-symlink and descendant tests before claiming those platform checks passed.

## Upstream verification actually performed

Read-only official GitHub API queries for `/releases/latest` and `/releases/tags/DepotDownloader_3.4.0` both resolved **DepotDownloader 3.4.0**. Selected official asset:

- Name: `DepotDownloader-linux-arm64.zip`
- Size: **32,026,406 bytes**
- API digest: **null** (no published asset SHA256 in that release metadata)
- Published: `2025-05-09T19:43:45Z`
- URL: `https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_3.4.0/DepotDownloader-linux-arm64.zip`

A real HTTPS artifact download, ZIP parse and safe extractor invocation succeeded locally. ZIP contained `DepotDownloader` and `LICENSE`. Native executable ELF header was `7f454c460201010000000000000000000300b700` (AArch64 e_machine bytes `b700`). Observed SHA256:

```
d9fb612ccebc1db8eeea3b4045d2221ec70431381393ce908fb72f01d4f9c812
```

The binary was **not executed on Windows**, and the downloaded archive is not redistributed. The observed hash is not a publisher signature. Runtime install verifies a published digest when available, and an optional operator digest when supplied, and records provenance.

## Parent/operator integration gates — not claimed locally

The parent owns a **serial, newly isolated ARM64 Docker harness**; no Panel/OCI/host/firewall changes or heavy remote tests were performed by this module's worker.

Before publishing a tested-runtime claim, exercise the exact exported scripts and images:

1. Native root installer image runs the embedded installer, obtains the official anonymous Linux depot and leaves native x86-64 ELF `game/7DaysToDieServer.x86_64` mode 0755 plus an actual shipped persistent config. Record resolved depot manifest/build/version; don't label requested branch alone as a verified version.
2. Run as the runtime image's non-root user, with a writable owned volume and adequate RAM/disk. Verify stdout logging reaches the bridge, the real current V3.3 marker matches, listener addresses are actually loopback-only, management has no allocations, dashboard is disabled and no game target-FPS override appears.
3. Complete a real ready-state stdin command/response (`gettime`), normal `shutdown`/save/exit0, actual SIGTERM/save/exit0, restart and offline reinstall. Check current root XML/world/admin files remain preserved; no old trial settings/credentials/manifest are imposed.
4. Check `USER_XML_MODE=user` preserves real custom config and SandboxCode while keeping required management safety. Verify malformed XML failure leaves the file unchanged. Verify blank SandboxCode does not apply guessed gameplay defaults.
5. Confirm inherited image entrypoint/process group behavior allows Wings Stop with a grace longer than the Egg's deadline, and that a forced/unexpected exit remains nonzero.
6. Real client login, EAC/crossplay restrictions, selected experimental branch, mod compatibility, full-save recovery, resource sizing, multiplayer performance and long-duration soak remain separate tests. Do not infer them from local fixtures or mere process existence.

## CI/publication handoff

Suitable offline CI matrix: Linux Python 3.11 and 3.13, optionally a native ARM runner. Use stdlib unittest, Python syntax checks, `bash -n install.sh`, and rebuild followed by a generated-file diff. **Do not run the multi-GB game installer in routine CI.** All local tests are independent of network/Steam credentials; only the separately reported upstream check used network.

`build_egg.py` keeps `UPDATE_URL = None` for default local builds and supports both `make_egg(update_url=...)` and the publication CLI `python build_egg.py --update-url PUBLIC_EGG_JSON_URL`. After tests, the parent supplies the verified public download URL and regenerates both artifacts; no source-constant edit is needed. The CLI test runs a copied module in a temporary directory, so it cannot replace release artifacts with null-URL snapshots. The fixed newly generated `EGG_UUID` is `a2ea934e-37f4-41eb-93b5-49e060f033bd`; `uuid.UUID` validity/version and repeated-build stability are covered. Distinct forks must choose their own fixed UUID and update URL. Git/repository creation, Actions workflows and Pelican import are parent-owned; none were mutated here. This follow-up made no remote/network calls and ran no real-game integration.
