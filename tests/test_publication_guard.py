"""Publication guard tests; fixtures are synthetic, never live exports."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("publication_guard", ROOT / "scripts/publication_guard.py")
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def example_egg():
    return {
        "meta": {"version": "PLCN_v3", "update_url": "https://github.com/example/repo/releases/latest/download/egg.json"},
        "name": "Synthetic test Egg", "author": "example@users.noreply.github.com",
        "description": "Offline test fixture", "docker_images": {"Runtime": "example/runtime:1"},
        "startup_commands": {"Default": "./start.sh {{GAME_VERSION}}"},
        "config": {"files": {}, "startup": {"done": "Ready"}, "logs": {}, "stop": "stop"},
        "scripts": {"installation": {"script": "#!/bin/bash\nset -eu\nprintf '%s\\n' ready\n", "container": "example/installer:1", "entrypoint": "bash"}},
        "variables": [{"name": "Version", "description": "Game version", "env_variable": "GAME_VERSION",
                       "default_value": "latest", "rules": ["required", "string", "in:latest,stable"],
                       "user_viewable": True, "user_editable": True}],
    }


class EggGuardTests(unittest.TestCase):
    def validate(self, egg):
        validator = getattr(guard, "validate_egg", None)
        self.assertIsNotNone(validator, "validate_egg must implement semantic publication checks")
        validator(egg, "example/repo", "egg.json")

    def test_rejects_invalid_variables_and_defaults(self):
        cases = [
            ("env_variable", "bad-name"), ("default_value", []),
            ("default_value", "unsupported"), ("rules", []),
            ("rules", ["required", "string", "max:2"]),
            ("user_viewable", "true"), ("user_editable", 1),
            ("name", ""), ("description", None),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                egg = example_egg()
                egg["variables"][0][key] = value
                with self.assertRaises(ValueError):
                    self.validate(egg)
        egg = example_egg()
        egg["variables"].append(copy.deepcopy(egg["variables"][0]))
        with self.assertRaises(ValueError):
            self.validate(egg)
        egg = example_egg()
        egg["startup_commands"]["Default"] += " {{UNDECLARED_OPTION}}"
        with self.assertRaises(ValueError):
            self.validate(egg)
        egg = example_egg()
        egg["variables"][0].update(default_value="-1", rules=["required", "integer", "min:0", "max:10"])
        with self.assertRaises(ValueError):
            self.validate(egg)
        egg["variables"][0]["default_value"] = "5"
        self.validate(egg)

    def test_rejects_private_data_and_nonportable_update_urls(self):
        for url in (None, "http://github.com/example/repo/releases/latest/download/egg.json",
                    "https://github.com/other/repo/releases/latest/download/egg.json",
                    "https://raw.githubusercontent.com/example/repo/main/egg.json"):
            with self.subTest(url=url):
                egg = example_egg()
                egg["meta"]["update_url"] = url
                with self.assertRaises(ValueError):
                    self.validate(egg)
        for private in ("ocid1.instance.oc1.test", "-----BEGIN PRIVATE KEY-----",
                        "ghp_" + "x" * 36, "github_pat_" + "x" * 30,
                        "C:\\Users\\someone\\server", "/home/ubuntu/private",
                        "https://server.example.internal/data", "192.168.1.44", "203.0.113.20"):
            with self.subTest(marker=private):
                egg = example_egg()
                egg["description"] = private
                with self.assertRaises(ValueError):
                    self.validate(egg)
        for name, value in (("TELNET_PASSWORD", "changeme"), ("STEAM_PASSWORD", "a-secret"),
                            ("ACCEPT_EULA", "true")):
            egg = example_egg()
            egg["variables"].append({"name": name, "description": "User input only", "env_variable": name,
                                     "default_value": value, "rules": ["nullable", "string"],
                                     "user_viewable": True, "user_editable": True})
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(egg)
        egg = example_egg()
        egg["description"] = "Loopback 127.0.0.1 and bind 0.0.0.0 are generic."
        self.validate(egg)

    def test_rejects_serialized_or_malformed_native_config(self):
        for key, value in (("files", "{}"), ("startup", "{}"), ("logs", "{}"), ("stop", None)):
            with self.subTest(key=key):
                egg = example_egg()
                egg["config"][key] = value
                with self.assertRaises(ValueError):
                    self.validate(egg)

    def test_accepts_native_schema_and_rejects_incomplete_exports(self):
        self.validate(example_egg())
        for key in ("meta", "name", "author", "docker_images", "startup_commands", "config", "scripts", "variables"):
            with self.subTest(missing=key):
                egg = example_egg()
                del egg[key]
                with self.assertRaises(ValueError):
                    self.validate(egg)
        egg = example_egg()
        egg["meta"]["version"] = "PTDL_v2"
        with self.assertRaises(ValueError):
            self.validate(egg)


class BuildGuardTests(unittest.TestCase):
    def fixture(self, root):
        # This minimal builder is test-only; it does not represent either game's builder.
        egg = example_egg()
        text = json.dumps(egg, indent=2) + "\n"
        (root / "egg.json").write_text(text, encoding="utf-8", newline="\n")
        (root / "build_egg.py").write_text(
            "import argparse, pathlib\np=argparse.ArgumentParser()\np.add_argument('--update-url', required=True)\n"
            "a=p.parse_args()\nassert a.update_url == 'https://github.com/example/repo/releases/latest/download/egg.json'\n"
            "pathlib.Path('egg.json').write_bytes(" + repr(text.encode("utf-8")) + ")\n",
            encoding="utf-8")
        return text

    def test_cli_reads_metadata_and_fails_closed_on_unsafe_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            config = {"repository": "example/repo", "eggfile": "egg.json"}
            metadata = root / ".publication.json"
            metadata.write_text(json.dumps(config), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts/publication_guard.py"), "--root", str(root), "--repo", "example/repo", "--verify-build"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Publication checks passed", result.stdout)
            for bad_config in ({**config, "eggfile": "../egg.json"},
                               {**config, "repository": "owner/repo\nrun: evil"},
                               {"repository": "example/repo"}):
                with self.subTest(config=bad_config):
                    metadata.write_text(json.dumps(bad_config), encoding="utf-8")
                    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
                    self.assertNotEqual(result.returncode, 0)
            metadata.write_text(json.dumps(config), encoding="utf-8")
            (root / "egg.json").write_text("{}", encoding="utf-8")
            result = subprocess.run(command[:-1], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)

    def test_build_rejects_unsafe_identifiers_before_reading_files(self):
        with tempfile.TemporaryDirectory() as temp:
            for repo, eggfile in (("owner/repo", "../egg.json"), ("owner/repo\nrun: evil", "egg.json")):
                with self.subTest(repo=repo, eggfile=eggfile):
                    try:
                        guard.verify_build(Path(temp), repo, eggfile)
                    except Exception as error:
                        self.assertIsInstance(error, ValueError, "Reject identifiers before filesystem access")
                    else:
                        self.fail("Unsafe publication identifiers were accepted")

    def test_build_detects_nondeterminism_independently_of_git(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with (root / "build_egg.py").open("a", encoding="utf-8") as handle:
                handle.write("counter=pathlib.Path('counter')\nn=int(counter.read_text())+1 if counter.exists() else 1\n"
                             "counter.write_text(str(n))\nwith pathlib.Path('egg.json').open('ab') as f: f.write(b' '*n)\n")
            with self.assertRaisesRegex(ValueError, "byte-deterministic"):
                guard.verify_build(root, "example/repo", "egg.json")

    def test_build_accepts_lf_shell_control_flow_without_text_translation(self):
        # Git Bash may briefly retain a failed parser's cwd on Windows.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "good.sh").write_bytes(b"#!/bin/bash\nif true; then\n  (printf '%s\\n' ready)\nfi\n")
            try:
                guard.verify_build(root, "example/repo", "egg.json")
            except ValueError as error:
                self.fail(f"Valid LF shell source was rejected: {error}")

    def test_build_checks_real_cli_determinism_and_shell_sources(self):
        verifier = getattr(guard, "verify_build", None)
        self.assertIsNotNone(verifier, "verify_build must exercise the actual builder twice")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = self.fixture(root)
            verifier(root, "example/repo", "egg.json")
            self.assertEqual((root / "egg.json").read_text(encoding="utf-8"), original)
            # A module shell syntax error must block publication without executing it.
            (root / "start.sh").write_text("#!/bin/bash\nif then\n", encoding="utf-8")
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                verifier(root, "example/repo", "egg.json")
            (root / "start.sh").unlink()
            with (root / "build_egg.py").open("a", encoding="utf-8") as handle:
                handle.write("with pathlib.Path('egg.json').open('ab') as f: f.write(b' ')\n")
            # Different from the tracked export even though still valid JSON.
            with self.assertRaises(ValueError):
                verifier(root, "example/repo", "egg.json")


class WorkflowPolicyTests(unittest.TestCase):
    def test_ci_is_read_only_and_all_remote_actions_are_sha_pinned(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("\npermissions:\n  contents: read\n", ci)
        self.assertNotIn("contents: write", ci)
        self.assertIn("  pull_request:\n", ci)
        self.assertIn("  workflow_call:\n", ci)
        for text in (ci, release):
            for forbidden in ("pull_request_target", "workflow_run", "secrets.", "secrets: inherit", "id-token:", "write-all", "self-hosted"):
                self.assertNotIn(forbidden, text)
            for line in text.splitlines():
                if "uses:" in line and "./" not in line:
                    self.assertRegex(line, r"uses: actions/[a-z-]+@[0-9a-f]{40} # v[0-9.]+$")
            self.assertEqual(text.count("uses: actions/checkout@"), text.count("persist-credentials: false"))
        self.assertIn("os: [ubuntu-24.04, ubuntu-24.04-arm]", ci)
        self.assertIn("python: ['3.11', '3.13']", ci)
        self.assertIn("python -W error -m unittest", ci)
        self.assertIn("python -W error -m compileall", ci)
        self.assertIn("--verify-build", ci)
        self.assertIn('git diff --exit-code -- "$EGG_FILE"', ci)

    def test_release_is_tag_only_ci_gated_and_scopes_credentials(self):
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("on:\n  push:\n    tags: ['v*']\n", release)
        self.assertIn("\npermissions:\n  contents: read\n", release)
        self.assertIn("uses: ./.github/workflows/ci.yml", release)
        self.assertIn("  publish:\n    needs: ci\n", release)
        self.assertIn("if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')", release)
        self.assertEqual(release.count("contents: write"), 1)
        self.assertIn("    permissions:\n      contents: write\n", release)
        self.assertIn("GH_TOKEN: ${{ github.token }}", release)
        self.assertIn("[[ \"$RELEASE_TAG\" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]", release)
        self.assertIn("--verify-tag --latest", release)
        self.assertNotIn("--clobber", release)
        self.assertIn("gh release download", release)
        self.assertIn("sha256sum --check SHA256SUMS", release)
        self.assertIn('cmp -- "dist/$EGG_FILE" "verified/$EGG_FILE"', release)
        # Event/ref/repository values must enter the shell through quoted env vars.
        in_run = False
        for line in release.splitlines():
            if line.lstrip().startswith("run:"):
                in_run = True
            elif in_run and line.startswith("          "):
                self.assertNotIn("${{", line)
            else:
                in_run = False


if __name__ == "__main__":
    unittest.main()
