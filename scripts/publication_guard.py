"""Offline publication checks for standalone native Pelican Eggs (Python 3.11+)."""
import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def verify_build(root, repo, eggfile):
    """Run the offline builder twice and check drift plus shell syntax, not a game."""
    validate_identifiers(repo, eggfile)
    root = Path(root)
    output = root / eggfile
    before = output.read_bytes()
    snapshots = []
    for _ in range(2):
        subprocess.run([sys.executable, "-W", "error", "build_egg.py", "--update-url",
                        f"https://github.com/{repo}/releases/latest/download/{eggfile}"],
                       cwd=root, check=True, timeout=120)
        snapshots.append(output.read_bytes())
        validate_egg(json.loads(snapshots[-1]), repo, eggfile)
    if snapshots[0] != snapshots[1]:
        raise ValueError("Builder is not byte-deterministic")
    if snapshots[0] != before:
        raise ValueError("Committed export differs from rebuilt Egg; rebuild and review before publishing")
    sources = [(str(path.relative_to(root)), path.read_bytes())
               for path in root.rglob("*") if path.is_file() and path.suffix in (".sh", ".bash") and ".git" not in path.parts]
    egg = json.loads(snapshots[0])
    sources.append(("embedded installer", egg["scripts"]["installation"]["script"].encode("utf-8")))
    for name, source in sources:
        result = subprocess.run(["bash", "-n"], input=source, capture_output=True, timeout=30)
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"Shell syntax error in {name}: {detail}")


def validate_egg(egg, repo, eggfile):
    """Validate the maintained PLCN_v3 publication subset, not Panel compatibility."""
    required = ("meta", "name", "author", "docker_images", "startup_commands", "config", "scripts", "variables")
    if not isinstance(egg, dict) or any(key not in egg for key in required):
        raise ValueError("Egg is missing required native export fields")
    if not isinstance(egg["meta"], dict) or egg["meta"].get("version") != "PLCN_v3":
        raise ValueError("Native PLCN_v3 export required")
    expected_url = f"https://github.com/{repo}/releases/latest/download/{eggfile}"
    if egg["meta"].get("update_url") != expected_url:
        raise ValueError("meta.update_url must match this repository's stable release asset URL")
    pending = [egg]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            if re.search(r"ocid1\.|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|[A-Za-z]:[\\/]Users[\\/]|/home/(?!container(?:/|\b))[A-Za-z0-9_-]+|\.internal\b", item, re.I):
                raise ValueError("Potential secret, cloud identifier or personal host path in Egg")
            for address in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", item):
                try:
                    ip = ipaddress.ip_address(address)
                except ValueError:
                    continue
                if not ip.is_loopback and address not in ("0.0.0.0", "255.255.255.255"):
                    raise ValueError("Non-generic IP literal in Egg; use a user variable")
    for key in ("name", "author"):
        if not isinstance(egg[key], str) or not egg[key].strip():
            raise ValueError(f"{key} must be nonempty text")
    for key in ("docker_images", "startup_commands"):
        if not isinstance(egg[key], dict) or not egg[key] or not all(
                isinstance(k, str) and k and isinstance(v, str) and v.strip()
                for k, v in egg[key].items()):
            raise ValueError(f"{key} must be a nonempty text mapping")
    config = egg["config"]
    if not isinstance(config, dict) or any(key not in config for key in ("files", "startup", "logs", "stop")):
        raise ValueError("config must contain files, startup, logs and stop")
    if any(not isinstance(config[key], dict) for key in ("files", "startup", "logs")) or not isinstance(config["stop"], str) or not config["stop"]:
        raise ValueError("Native config requires objects and a nonempty stop command")
    if not isinstance(egg["scripts"], dict) or not isinstance(egg["scripts"].get("installation"), dict):
        raise ValueError("Installation script required")
    install = egg["scripts"]["installation"]
    if any(not isinstance(install.get(key), str) or not install[key].strip()
           for key in ("script", "container", "entrypoint")):
        raise ValueError("Installation script, container and entrypoint required")
    if not isinstance(egg["variables"], list) or not egg["variables"]:
        raise ValueError("variables must be a nonempty list")
    names = set()
    for variable in egg["variables"]:
        if not isinstance(variable, dict):
            raise ValueError("Variable must be an object")
        name = variable.get("env_variable")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or name in names:
            raise ValueError("Variable environment names must be unique uppercase identifiers")
        names.add(name)
        if any(type(variable.get(flag)) is not bool for flag in ("user_viewable", "user_editable")):
            raise ValueError(f"{name}: explicit boolean visibility/editability required")
        if not isinstance(variable.get("name"), str) or not variable["name"].strip() or not isinstance(variable.get("description"), str):
            raise ValueError(f"{name}: name and description must be text")
        value, rules = variable.get("default_value"), variable.get("rules")
        if not isinstance(value, str) or not isinstance(rules, list) or not rules or not all(isinstance(rule, str) and rule for rule in rules):
            raise ValueError(f"{name}: text default and nonempty native validation rules required")
        if re.search(r"(?:PASSWORD|PASSWD|TOKEN|SECRET|STEAM_USER(?:NAME)?)", name) and value:
            raise ValueError(f"{name}: credentials must have empty defaults")
        if "EULA" in name and value.lower() not in ("", "false", "0"):
            raise ValueError(f"{name}: license acceptance must be explicitly opt-in")
        if not value and "nullable" in rules:
            continue
        if "required" in rules and not value:
            raise ValueError(f"{name}: required default is empty")
        integer = "integer" in rules
        if integer and not re.fullmatch(r"-?[0-9]+", value):
            raise ValueError(f"{name}: integer default required")
        if "boolean" in rules and value not in ("0", "1", "true", "false"):
            raise ValueError(f"{name}: boolean default required")
        for rule in rules:
            if rule.startswith("in:") and value not in rule[3:].split(","):
                raise ValueError(f"{name}: default not in permitted values")
            if rule.startswith(("min:", "max:")):
                size = int(value) if integer else len(value)
                bound = int(rule.split(":", 1)[1])
                if (rule.startswith("min:") and size < bound) or (rule.startswith("max:") and size > bound):
                    raise ValueError(f"{name}: default outside validation limits")
    references = set(re.findall(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}", json.dumps(egg)))
    builtins = {"SERVER_MEMORY", "SERVER_IP", "SERVER_PORT", "SERVER_UUID", "SERVER_NAME", "SERVER_LOCATION", "STARTUP"}
    if references - names - builtins:
        raise ValueError("Unknown templated environment variables: " + ", ".join(sorted(references - names - builtins)))


def validate_identifiers(repo, eggfile):
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", repo):
        raise ValueError("repository must be safe GitHub OWNER/NAME")
    if not isinstance(eggfile, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.json", eggfile):
        raise ValueError("eggfile must be a safe .json basename")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repo", help="Override GITHUB_REPOSITORY for a local check")
    parser.add_argument("--verify-build", action="store_true")
    args = parser.parse_args()
    try:
        config = json.loads((args.root / ".publication.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Publication metadata must be an object")
        eggfile = config.get("eggfile")
        validate_identifiers(config.get("repository"), eggfile)
        repo = args.repo or os.environ.get("GITHUB_REPOSITORY") or config["repository"]
        validate_identifiers(repo, eggfile)
        if args.verify_build:
            verify_build(args.root, repo, eggfile)
        else:
            validate_egg(json.loads((args.root / eggfile).read_text(encoding="utf-8")), repo, eggfile)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Publication check failed: {error}\n")
    print("Publication checks passed (offline; not a live Pelican/game test).")


if __name__ == "__main__":
    main()
