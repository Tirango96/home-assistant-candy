"""
ci_vm.py — copy local candy component to the test VM and run the full CI suite.

Usage:
    python tools/ci_vm.py            # copy + run all checks
    python tools/ci_vm.py --setup    # force re-create venv and reinstall deps
    python tools/ci_vm.py --check    # run CI without copying files

The script is idempotent: it clones the repo and creates the venv only when
they are absent, so a rebooted VM is handled transparently in one execution.
"""

from __future__ import annotations

import argparse
import os
import sys

import paramiko

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VM_HOST = "omv-test"
VM_USER = "root"
VM_PASSWORD = "VMware1!"

REMOTE_DIR = "/tmp/candy-ci-test"
REPO_URL = "https://github.com/bigmoby/home-assistant-candy.git"

LOCAL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)

# Directories inside custom_components/candy/ to sync (all .py and .json files)
COMPONENT_LOCAL = os.path.join(LOCAL_ROOT, "custom_components", "candy")
COMPONENT_REMOTE = f"{REMOTE_DIR}/custom_components/candy"

TESTS_LOCAL = os.path.join(LOCAL_ROOT, "tests")
TESTS_REMOTE = f"{REMOTE_DIR}/tests"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(client: paramiko.SSHClient, cmd: str, timeout: int = 300) -> tuple[int, str]:
    """Run a command and return (exit_code, combined_output)."""
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    combined = (out + err).strip()
    return rc, combined


def _print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("=" * 60)


def _sftp_put_tree(sftp: paramiko.SFTPClient, client: paramiko.SSHClient, local_dir: str, remote_dir: str) -> int:
    """Recursively copy all .py and .json files. Returns number of files copied."""
    count = 0
    for root, _dirs, files in os.walk(local_dir):
        rel = os.path.relpath(root, local_dir)
        remote_subdir = remote_dir if rel == "." else f"{remote_dir}/{rel.replace(os.sep, '/')}"
        _run(client, f"mkdir -p {remote_subdir}")
        for fname in files:
            if fname.endswith((".py", ".json")):
                sftp.put(os.path.join(root, fname), f"{remote_subdir}/{fname}")
                count += 1
    return count


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def ensure_repo(client: paramiko.SSHClient) -> None:
    """Clone repo if absent; do nothing if it already exists."""
    rc, _ = _run(client, f"test -d {REMOTE_DIR}/.git")
    if rc == 0:
        print("  Repo already present — skipping clone")
        return
    print("  Cloning repo …")
    rc, out = _run(client, f"git clone {REPO_URL} {REMOTE_DIR}", timeout=120)
    if rc != 0:
        print(f"  ERROR: git clone failed:\n{out}")
        sys.exit(1)
    print("  Clone done")


def ensure_venv(client: paramiko.SSHClient, force: bool = False) -> None:
    """Create venv and install deps if absent (or if force=True)."""
    venv_python = f"{REMOTE_DIR}/.venv/bin/python"
    rc, _ = _run(client, f"test -x {venv_python}")
    if rc == 0 and not force:
        print("  Venv already present — skipping setup")
        return
    print("  Creating venv and installing deps (this takes ~60s) …")
    cmd = (
        f"cd {REMOTE_DIR} && "
        "python3 -m venv .venv && "
        ".venv/bin/pip install --quiet "
        "-r requirements.txt -r requirements-dev.txt -r requirements.test.txt"
    )
    rc, out = _run(client, cmd, timeout=300)
    if rc != 0:
        print(f"  ERROR: venv setup failed:\n{out[-2000:]}")
        sys.exit(1)
    print("  Venv ready")


def copy_files(client: paramiko.SSHClient) -> None:
    """Sync local component + test files to the VM."""
    sftp = client.open_sftp()
    n = _sftp_put_tree(sftp, client, COMPONENT_LOCAL, COMPONENT_REMOTE)
    n += _sftp_put_tree(sftp, client, TESTS_LOCAL, TESTS_REMOTE)
    sftp.close()
    print(f"  Copied {n} files")


def run_ci(client: paramiko.SSHClient) -> bool:
    """Run all four CI checks. Returns True if all pass."""
    venv = f"{REMOTE_DIR}/.venv/bin"
    checks = [
        ("ruff check",       f"{venv}/ruff check {REMOTE_DIR}"),
        ("ruff format",      f"{venv}/ruff format --check {REMOTE_DIR}"),
        ("mypy",             f"{venv}/mypy {REMOTE_DIR}/custom_components/candy"),
        ("pytest",           f"{venv}/pytest --asyncio-mode=auto -q {REMOTE_DIR}"),
    ]
    all_passed = True
    for name, cmd in checks:
        print(f"\n  [{name}] …", end="", flush=True)
        rc, out = _run(client, f"cd {REMOTE_DIR} && {cmd}", timeout=180)
        if rc == 0:
            print(" PASS")
        else:
            print(f" FAIL (exit {rc})")
            # Print only the relevant lines — skip long INFO/DEBUG log noise
            lines = out.splitlines()
            signal_lines = [
                l for l in lines
                if any(
                    k in l
                    for k in ("error:", "Error", "FAILED", "failed", "warning:", "Warning", "short test summary")
                )
            ]
            # Fall back to last 40 lines if nothing matches
            output = "\n".join(signal_lines) if signal_lines else "\n".join(lines[-40:])
            print(output)
            all_passed = False
    return all_passed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="CI helper for the candy integration VM")
    parser.add_argument("--setup", action="store_true", help="Force re-create venv")
    parser.add_argument("--check", action="store_true", help="Run CI without copying files")
    args = parser.parse_args()

    print(f"Connecting to {VM_USER}@{VM_HOST} …")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(VM_HOST, username=VM_USER, password=VM_PASSWORD, timeout=10)
    except Exception as e:
        print(f"ERROR: Cannot reach VM: {e}")
        print("Is the VM running? Check with: ping omv-test")
        sys.exit(1)
    print("Connected")

    _print_section("1/3  Environment")
    ensure_repo(client)
    ensure_venv(client, force=args.setup)

    if not args.check:
        _print_section("2/3  Sync files")
        copy_files(client)
    else:
        print("\n  [--check mode: skipping file copy]")

    _print_section("3/3  CI")
    passed = run_ci(client)

    client.close()

    print("\n" + ("=" * 60))
    if passed:
        print("  ALL CHECKS PASSED")
    else:
        print("  SOME CHECKS FAILED — see output above")
    print("=" * 60 + "\n")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
