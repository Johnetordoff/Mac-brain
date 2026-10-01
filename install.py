#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
APP = HOME / ".macbrain"
RUNTIME = APP / "runtime"
MODELS = APP / "models"
VENDOR = APP / "vendor"
MODEL = MODELS / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true"
MODEL_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
LLAMA_TAG = "b4400"
LLAMA_COMMIT = "6e1531aca5ed17f078973b4700fcdadbda4a34a5"
LLAMA_REPO = "https://github.com/ggml-org/llama.cpp.git"


def sh(args, *, check=True, capture=False, cwd=None, input_text=None):
    return subprocess.run(
        args,
        check=check,
        text=True,
        input=input_text,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )



def network_service_for_interface(interface: str) -> str:
    """Return the macOS network service name corresponding to a BSD interface."""
    result = sh(["/usr/sbin/networksetup", "-listnetworkserviceorder"], check=False, capture=True)
    current = ""
    for raw in (result.stdout or "").splitlines():
        line = raw.strip()
        if line.startswith("(") and ") " in line and "Hardware Port:" not in line:
            current = line.split(") ", 1)[1].strip()
            if current.startswith("*"):
                current = current[1:].strip()
        if f"Device: {interface})" in line and current:
            return current
    return ""


def sudo_auth() -> threading.Event:
    print("Administrator authentication is required. macOS sudo will ask for your password now.")
    print("Mac Brain does not read, echo, store, or pass your password to the local model.")
    p = subprocess.run(["sudo", "-v"])
    if p.returncode != 0:
        raise SystemExit("sudo authentication failed")
    stop = threading.Event()

    def keepalive():
        while not stop.wait(50):
            subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    threading.Thread(target=keepalive, daemon=True).start()
    return stop


def preflight(allow_sip_disabled: bool) -> dict:
    if platform.system() != "Darwin":
        raise SystemExit("Mac Brain bootstrap must be run on macOS.")
    ver = platform.mac_ver()[0]
    arch = platform.machine()
    print(f"Detected macOS {ver or 'unknown'} on {arch}.")
    if arch != "x86_64":
        raise SystemExit("This first Mac Brain build is intentionally targeted at Intel x86_64.")
    if ver and not ver.startswith("11.7."):
        print("WARNING: first target is Big Sur 11.7.x; continuing, but this exact OS has not been the primary target.")
    if sys.version_info < (3, 8):
        raise SystemExit(f"Python 3.8+ required; found {sys.version.split()[0]}")
    if not Path("/usr/bin/git").exists():
        raise SystemExit("/usr/bin/git is missing. The three-command install requires Apple Command Line Tools.")

    sip = sh(["/usr/bin/csrutil", "status"], check=False, capture=True)
    sip_text = ((sip.stdout or "") + (sip.stderr or "")).strip()
    print(sip_text)
    if "disabled" in sip_text.lower() and not allow_sip_disabled:
        raise SystemExit("SIP appears disabled. Re-enable SIP, or explicitly rerun with --allow-sip-disabled.")

    gateway = ""
    interface = "en0"
    route = sh(["/sbin/route", "-n", "get", "default"], check=False, capture=True)
    for line in (route.stdout or "").splitlines():
        text = line.strip()
        if text.startswith("gateway:"):
            gateway = text.split(":", 1)[1].strip()
        elif text.startswith("interface:"):
            interface = text.split(":", 1)[1].strip() or interface

    local_ip = sh(["/usr/sbin/ipconfig", "getifaddr", interface], check=False, capture=True).stdout.strip()
    netmask = sh(["/usr/sbin/ipconfig", "getoption", interface, "subnet_mask"], check=False, capture=True).stdout.strip()
    lan_cidr = ""
    if local_ip and netmask:
        try:
            lan_cidr = str(ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False))
        except ValueError:
            pass

    network_service = network_service_for_interface(interface)

    mem = sh(["/usr/sbin/sysctl", "-n", "hw.memsize"], check=False, capture=True).stdout.strip()
    try:
        memory_bytes = int(mem)
    except ValueError:
        memory_bytes = 0

    return {
        "macos": ver,
        "arch": arch,
        "python": str(Path(sys.executable).resolve()),
        "gateway": gateway,
        "interface": interface,
        "local_ip": local_ip,
        "netmask": netmask,
        "lan_cidr": lan_cidr,
        "network_service": network_service,
        "memory_bytes": memory_bytes,
        "repo": str(ROOT),
    }


def authorized_ssh_source(info: dict, input_fn=input) -> str:
    """Choose exactly one IPv4 controller host for the post-arm SSH doorway.

    A whole LAN CIDR is intentionally not accepted: after takeover, only the user's
    controller computer should be able to initiate an IP connection to Mac Brain.
    """
    parts = os.environ.get("SSH_CONNECTION", "").split()
    candidate = ""
    if parts:
        try:
            candidate = str(ipaddress.IPv4Address(parts[0]))
            print(f"Detected current SSH controller: {candidate}")
        except ipaddress.AddressValueError:
            candidate = ""
    env_candidate = os.environ.get("MACBRAIN_CONTROLLER_IP", "").strip()
    if not candidate and env_candidate:
        try:
            candidate = str(ipaddress.IPv4Address(env_candidate))
        except ipaddress.AddressValueError:
            raise SystemExit("MACBRAIN_CONTROLLER_IP is not a valid IPv4 address. Network isolation was NOT applied.")
    if not candidate:
        print("Mac Brain needs the IPv4 address of the ONE other computer that will be allowed to SSH in after takeover.")
        candidate = input_fn("Controller computer IPv4 address: ").strip()
        try:
            candidate = str(ipaddress.IPv4Address(candidate))
        except ipaddress.AddressValueError:
            raise SystemExit("Controller address is not valid IPv4. Network isolation was NOT applied.")
    cidr = str(info.get("lan_cidr", ""))
    if cidr:
        try:
            if ipaddress.IPv4Address(candidate) not in ipaddress.IPv4Network(cidr, strict=False):
                raise SystemExit(
                    f"Controller {candidate} is not on Mac Brain's directly attached LAN {cidr}. "
                    "Takeover deliberately requires same-LAN IPv4 SSH so the default Internet route can be removed."
                )
        except ValueError:
            pass
    return candidate


def viability_assessment(*, memory_bytes: int, disk_free_bytes: int, battery_source: str, cpu_count: int, load1: float) -> dict:
    blockers = []
    warnings = []
    gib = 1024 ** 3
    if memory_bytes and memory_bytes < 4 * gib:
        blockers.append("less than 4 GiB of physical RAM")
    if disk_free_bytes < 4 * gib:
        blockers.append("less than 4 GiB of free disk space")
    elif disk_free_bytes < 8 * gib:
        warnings.append("free disk space is tight; cleanup should be an early priority")
    if battery_source and battery_source.lower() == "battery power":
        blockers.append("Mac is running on battery power; plug in AC before the long build/model download")
    elif battery_source and battery_source.lower() not in ("ac power", "unknown"):
        warnings.append(f"power source could not be confirmed as AC ({battery_source})")
    if cpu_count and load1 / max(cpu_count, 1) > 1.0:
        warnings.append("the machine is already heavily loaded before Mac Brain starts")
    return {"blockers": blockers, "warnings": warnings}


def early_viability_diagnostics(info: dict) -> None:
    print("\nRunning early Mac Brain viability diagnostics before downloads/builds...")
    cpu = sh(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], check=False, capture=True).stdout.strip()
    cpu_count_raw = sh(["/usr/sbin/sysctl", "-n", "hw.logicalcpu"], check=False, capture=True).stdout.strip()
    try:
        cpu_count = int(cpu_count_raw)
    except ValueError:
        cpu_count = os.cpu_count() or 1
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        load1 = 0.0
    disk = shutil.disk_usage("/")
    batt = sh(["/usr/bin/pmset", "-g", "batt"], check=False, capture=True).stdout
    battery_source = "unknown"
    marker = "Now drawing from '"
    if marker in batt:
        battery_source = batt.split(marker, 1)[1].split("'", 1)[0]
    memory_bytes = int(info.get("memory_bytes", 0) or 0)
    assessment = viability_assessment(
        memory_bytes=memory_bytes,
        disk_free_bytes=disk.free,
        battery_source=battery_source,
        cpu_count=cpu_count,
        load1=load1,
    )
    print(f"CPU: {cpu or 'unknown'} ({cpu_count} logical CPUs)")
    print(f"RAM: {memory_bytes / 1024**3:.1f} GiB" if memory_bytes else "RAM: unknown")
    print(f"Disk free: {disk.free / 1024**3:.1f} GiB of {disk.total / 1024**3:.1f} GiB")
    print(f"Current 1-minute load: {load1:.2f}; power source: {battery_source}")
    for warning in assessment["warnings"]:
        print(f"WARNING: {warning}.")
    if assessment["blockers"]:
        joined = "; ".join(assessment["blockers"])
        raise SystemExit(
            f"Mac Brain preflight stopped before large downloads/builds: {joined}. "
            "Networking is still normal and no containment was applied."
        )
    print("Basic hardware/storage viability check passed. Mac Brain will measure actual bottlenecks rather than assuming age is the cause.")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    """Download a large artifact with Big Sur's system curl.

    Using /usr/bin/curl avoids depending on the certificate bundle of whichever
    Python 3 happens to be installed on this old Mac. The .part file makes a slow
    or interrupted 1+ GiB model download resumable. SHA-256 verification happens
    separately before the file is ever trusted.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    curl = Path("/usr/bin/curl")
    if not curl.exists():
        raise SystemExit("/usr/bin/curl is missing. Network isolation was NOT applied.")

    existing = part.stat().st_size if part.exists() else 0
    print(f"Downloading {dest.name} ({'resuming' if existing else 'starting'})...")
    base = [
        str(curl), "-L", "--fail", "--show-error", "--progress-bar",
        "--retry", "5", "--retry-delay", "2", "--connect-timeout", "20",
    ]
    cmd = base + (["--continue-at", "-"] if existing else []) + ["--output", str(part), url]
    p = subprocess.run(cmd)
    if p.returncode != 0 and existing:
        # Some HTTP intermediaries refuse byte-range resume. Restart cleanly once
        # rather than making the user diagnose an opaque curl error.
        print("Resume was not accepted; restarting the model download from zero...")
        part.unlink(missing_ok=True)
        p = subprocess.run(base + ["--output", str(part), url])
    if p.returncode != 0:
        raise SystemExit("Model download failed after retries. Networking is still normal; rerun python3 install.py later to retry.")
    part.replace(dest)


def verify_command_line_tools() -> None:
    """Fail early if Apple's compiler toolchain is only a missing-tools stub."""
    xcode = sh(["/usr/bin/xcode-select", "-p"], check=False, capture=True)
    developer_dir = (xcode.stdout or "").strip()
    if xcode.returncode != 0 or not developer_dir:
        raise SystemExit(
            "Apple Command Line Tools are not installed/configured. Because git clone already depends on them on Big Sur, "
            "install the Command Line Tools first, then rerun the same three commands. Network isolation was NOT applied."
        )
    for exe in ("/usr/bin/git", "/usr/bin/make", "/usr/bin/cc", "/usr/bin/c++", "/usr/bin/curl"):
        if not Path(exe).exists():
            raise SystemExit(f"Required macOS tool missing: {exe}. Network isolation was NOT applied.")
    compiler = sh(["/usr/bin/cc", "--version"], check=False, capture=True)
    if compiler.returncode != 0:
        raise SystemExit("Apple clang is not runnable. Command Line Tools appear incomplete; network isolation was NOT applied.")
    print(f"Apple Command Line Tools: {developer_dir}")
    first = ((compiler.stdout or compiler.stderr or "").splitlines() or ["Apple clang"])[0]
    print(f"Compiler: {first}")


def llama_checkout_matches(src: Path) -> bool:
    """Return True only for the exact llama.cpp revision Mac Brain supports."""
    if not (src / "Makefile").exists():
        return False
    head = sh(
        ["/usr/bin/git", "-C", str(src), "rev-parse", "HEAD"],
        check=False, capture=True,
    )
    return head.returncode == 0 and (head.stdout or "").strip() == LLAMA_COMMIT


def build_runtime() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cli = RUNTIME / "llama-cli"
    if cli.exists():
        p = sh([str(cli), "--version"], check=False, capture=True)
        if p.returncode == 0:
            print("llama-cli already installed and runnable.")
            return
        cli.unlink()
    src = VENDOR / "llama.cpp"
    VENDOR.mkdir(parents=True, exist_ok=True)
    if src.exists() and not llama_checkout_matches(src):
        print(f"Replacing stale/incomplete llama.cpp checkout with pinned {LLAMA_TAG}...")
        shutil.rmtree(src, ignore_errors=True)
    if not src.exists():
        print(f"Cloning llama.cpp {LLAMA_TAG} before network isolation...")
        sh(["/usr/bin/git", "clone", "--depth", "1", "--branch", LLAMA_TAG, LLAMA_REPO, str(src)])
    if not llama_checkout_matches(src):
        raise SystemExit(
            f"llama.cpp checkout is not the expected pinned revision {LLAMA_COMMIT}. "
            "Networking is still normal; rerun python3 install.py to retry."
        )
    print("Building CPU-only llama.cpp for this Intel Mac (2 jobs, Metal disabled)...")
    env = os.environ.copy()
    env.update({"LLAMA_MAKEFILE": "1", "GGML_NO_METAL": "1", "GGML_NO_OPENMP": "1"})
    p = subprocess.run(["/usr/bin/make", "-j2", "llama-cli"], cwd=str(src), env=env)
    if p.returncode != 0:
        raise SystemExit(
            f"llama.cpp {LLAMA_TAG} build failed. Networking is still normal; "
            "review the compiler/linker output above."
        )
    built = src / "llama-cli"
    if not built.exists():
        raise SystemExit("llama.cpp build completed but llama-cli was not found.")
    shutil.copy2(built, cli)
    os.chmod(cli, 0o755)
    p = sh([str(cli), "--version"], check=False, capture=True)
    if p.returncode != 0:
        raise SystemExit("Built llama-cli does not run on this macOS version.")


def install_model() -> None:
    if MODEL.exists() and sha256(MODEL) == MODEL_SHA256:
        print("Local model already present and verified.")
        return
    if MODEL.exists():
        MODEL.unlink()
    download(MODEL_URL, MODEL)
    print("Verifying model SHA-256...")
    actual = sha256(MODEL)
    if actual != MODEL_SHA256:
        MODEL.unlink(missing_ok=True)
        raise SystemExit(f"Model checksum mismatch: got {actual}")
    print("Model verified.")


def write_config(info: dict, ssh_source: str) -> None:
    APP.mkdir(parents=True, exist_ok=True)
    config = {
        "mission": "speed_up_mac_brain",
        "sample_seconds": 60,
        "report_seconds": 120,
        "deep_scan_minutes": 30,
        "llm_synthesis_minutes": 15,
        "llm_threads": 2,
        "llm_context": 2048,
        "llm_predict": 320,
        "idle_load_per_cpu_max": 0.55,
        "model_path": str(MODEL),
        "llama_cli": str(RUNTIME / "llama-cli"),
        "quarantine_dir": str(APP / "quarantine"),
    }
    (APP / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(APP / "config.json", 0o600)
    # A fresh/re-run install always returns to the explicit two-stage handoff. Cheap proof-of-life
    # monitoring may run before takeover, but autonomous deep scans/AI do not start until
    # demonstration mode has passed AND low-level containment has been armed successfully.
    try:
        (APP / "mission.active").unlink()
    except FileNotFoundError:
        pass
    network = {
        "gateway_before_isolation": info.get("gateway", ""),
        "interface": info.get("interface", "en0"),
        "authorized_ssh_source": ssh_source,
        "network_service": info.get("network_service", ""),
    }
    (APP / "install-network.json").write_text(json.dumps(network, indent=2) + "\n")
    os.chmod(APP / "install-network.json", 0o600)


def write_launch_agent(info: dict) -> Path:
    src = (ROOT / "launchd" / "com.macbrain.performancehunter.plist.template").read_text()
    src = src.replace("__PYTHON__", info["python"]).replace("__REPO__", str(ROOT)).replace("__HOME__", str(HOME))
    agents = HOME / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    dest = agents / "com.macbrain.performancehunter.plist"
    dest.write_text(src)
    sh(["/bin/launchctl", "unload", str(dest)], check=False)
    return dest


def proof_of_life(timeout: float = 120.0) -> None:
    """Start the background worker and wait for it to record a NEW evidence sample.

    The plist intentionally has no RunAtLoad, so `launchctl load` alone never runs it;
    launch_worker() loads and explicitly starts it. Waiting for a fresh sample written
    by the worker (not the earlier first-mission pass) proves the worker really runs.
    """
    from macbrain import db
    from macbrain.lifecycle import CONTAINMENT_MARKER, launch_worker

    if CONTAINMENT_MARKER.exists():
        # Re-install on an already-armed Mac: the worker deliberately exits unless the
        # user has run `macbrain start` this boot, so it cannot be probed here.
        print("Containment is already armed; the worker will be verified by `macbrain start`.")
        return
    started = time.time()
    if not launch_worker():
        raise SystemExit("Background worker did not start. Network isolation was NOT applied.")
    while time.time() - started < timeout:
        recent = db.recent_samples(1)
        if recent and float(recent[0].get("ts", 0)) >= started:
            print("Performance Hunter background worker is running and recording evidence.")
            return
        time.sleep(2)
    raise SystemExit("Background worker started but recorded no evidence. Network isolation was NOT applied.")


def _ssh_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=3):
            return True
    except OSError:
        return False


def ensure_ssh() -> None:
    if _ssh_listening():
        print("SSH is already listening locally.")
        return
    raw = sh(["sudo", "-n", "/usr/sbin/systemsetup", "-getremotelogin"], check=False, capture=True)
    text = ((raw.stdout or "") + (raw.stderr or "")).strip()
    print(f"Remote Login: {text or 'unable to determine'}")
    print("Enabling Remote Login (SSH)...")
    sh(["sudo", "-n", "/usr/sbin/systemsetup", "-setremotelogin", "on"], check=False)
    time.sleep(1)
    if not _ssh_listening():
        # Big Sur can require Full Disk Access for systemsetup. Try loading Apple's
        # stock ssh launch daemon directly, but still verify before isolation.
        sh(["sudo", "-n", "/bin/launchctl", "load", "-w", "/System/Library/LaunchDaemons/ssh.plist"], check=False)
        time.sleep(1)
    if not _ssh_listening():
        raise SystemExit(
            "SSH is not listening on port 22. Enable System Preferences > Sharing > Remote Login, then rerun python3 install.py. Network isolation was NOT applied."
        )
    print("SSH listener verified on localhost:22.")


def arm_network_lock(ssh_source: str, interface: str, gateway: str, network_service: str, local_ip: str, netmask: str) -> None:
    print("\nMac Brain passed demonstration mode. The next step is the low-level containment handoff.")
    print(f"Controller allowed to initiate SSH: {ssh_source}")
    print("Mac Brain will block all other new IPv4/IPv6 traffic, remove the IPv4 default route, and disable IPv6 on the active network service when possible.")
    print("SSH reply packets are necessarily outbound packets belonging to the inbound SSH state; Mac Brain will not be allowed to initiate its own network connection.")
    print("Arming does NOT start the AI. Mac Brain stays OFF until you type START MAC BRAIN.")
    phrase = input("Type ARM MAC BRAIN to apply network containment: ").strip()
    if phrase != "ARM MAC BRAIN":
        raise SystemExit("Mac Brain was not armed. Networking remains normal and Mac Brain is OFF.")
    if not all((gateway, network_service, local_ip, netmask)):
        raise SystemExit("Could not identify the active IPv4 network service completely. Refusing takeover because hard no-egress containment cannot be guaranteed.")
    cmd = [
        "sudo", "-n", "/bin/bash", str(ROOT / "scripts" / "network_lock.sh"),
        "--source", ssh_source, "--interface", interface,
        "--gateway", gateway, "--service", network_service,
        "--ip", local_ip, "--netmask", netmask,
    ]
    sh(cmd)


def run_repo_self_test(info: dict) -> None:
    print("Running Mac Brain repository self-tests before installation...")
    env = os.environ.copy()
    env["MACBRAIN_HOME"] = str(APP / "selftest-state")
    p = subprocess.run(
        [info["python"], "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=str(ROOT), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
    )
    if p.returncode != 0:
        print(p.stdout or "")
        raise SystemExit("Mac Brain self-tests failed. Nothing has been isolated; fix the repo before continuing.")
    shutil.rmtree(APP / "selftest-state", ignore_errors=True)
    print("Repository self-tests passed.")


def runtime_smoke_test(info: dict) -> None:
    print("Smoke-testing the local Qwen model before network isolation...")
    cli = RUNTIME / "llama-cli"
    prompt = "<|im_start|>system\nAnswer with exactly: MAC BRAIN AWAKE<|im_end|>\n<|im_start|>user\nWake up.<|im_end|>\n<|im_start|>assistant\n"
    # Same argv builder as the runtime so the smoke test exercises the real invocation.
    # stdin is disconnected below so the local model can never wait on keyboard input.
    from macbrain.llm import llama_cli_args
    cmd = llama_cli_args(cli, MODEL, prompt, threads=2, context=512, predict=12, temp="0")
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=420, check=False)
    except subprocess.TimeoutExpired:
        raise SystemExit("Local-model smoke test timed out. Network isolation was NOT applied.")
    output = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    # Check stdout only: llama.cpp logs on stderr can echo prompt text and fake a pass.
    if p.returncode != 0 or "MAC BRAIN" not in (p.stdout or "").upper():
        print(output[-4000:])
        raise SystemExit("Local-model smoke test failed. Network isolation was NOT applied.")
    print("Local Qwen inference smoke test passed.")


def install_command_wrapper(info: dict) -> None:
    wrapper = APP / "macbrain-wrapper"
    wrapper.write_text(
        "#!/bin/sh\n"
        + f"cd {json.dumps(str(ROOT))} || exit 1\n"
        + f"exec {json.dumps(info['python'])} -m macbrain \"$@\"\n"
    )
    os.chmod(wrapper, 0o755)
    target = Path("/usr/local/bin/macbrain")
    sh(["sudo", "-n", "/bin/mkdir", "-p", "/usr/local/bin"])
    sh(["sudo", "-n", "/bin/cp", str(wrapper), str(target)])
    sh(["sudo", "-n", "/usr/sbin/chown", "root:wheel", str(target)])
    sh(["sudo", "-n", "/bin/chmod", "755", str(target)])
    print("Installed /usr/local/bin/macbrain command.")


def enable_wake_for_network() -> None:
    # Best effort: supported Intel Macs can wake for network access while on power.
    sh(["sudo", "-n", "/usr/bin/pmset", "-a", "womp", "1"], check=False)


def unload_agent() -> None:
    dest = HOME / "Library" / "LaunchAgents" / "com.macbrain.performancehunter.plist"
    sh(["/bin/launchctl", "unload", str(dest)], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Speed Up Mac Brain on the old Mac.")
    parser.add_argument("--allow-sip-disabled", action="store_true")
    args = parser.parse_args()

    # First interactive event: standard sudo authentication. Python never receives the password.
    keepalive = sudo_auth()
    armed = False
    try:
        info = preflight(args.allow_sip_disabled)
        ssh_source = ""
        mem_gb = info.get("memory_bytes", 0) / 1024**3 if info.get("memory_bytes") else 0
        print(f"Target profile: macOS {info.get('macos')}, {mem_gb:.1f} GB RAM. Controller SSH host will be selected only after demonstration mode.")
        APP.mkdir(parents=True, exist_ok=True)
        (APP / "quarantine").mkdir(exist_ok=True)

        verify_command_line_tools()
        run_repo_self_test(info)
        early_viability_diagnostics(info)
        build_runtime()
        install_model()
        write_config(info, ssh_source)
        install_command_wrapper(info)
        ensure_ssh()
        enable_wake_for_network()
        write_launch_agent(info)

        runtime_smoke_test(info)
        print("\nRunning Mac Brain's first mission baseline (non-destructive)...")
        sh([info["python"], "-m", "macbrain", "first-mission", "--no-llm"], cwd=ROOT)

        print("\nProof-of-life test: starting the background hunter before isolation...")
        proof_of_life()
        doctor = sh([info["python"], "-m", "macbrain", "doctor"], check=False, capture=True, cwd=ROOT)
        print((doctor.stdout or "").strip())
        if doctor.returncode != 0:
            raise SystemExit("Background proof-of-life failed. Network isolation was NOT applied.")
        unload_agent()
        print("Background proof-of-life passed.")

        print("\nMac Brain will now prove useful while ordinary networking is STILL NORMAL.")
        demo = subprocess.run([info["python"], "-m", "macbrain", "prearm-console"], cwd=str(ROOT))
        if demo.returncode != 0:
            raise SystemExit("Takeover was not approved. Networking remains normal and the autonomous mission did not start.")

        # Only after Mac Brain has demonstrated useful local reasoning do we ask which
        # single controller host will remain reachable through SSH after takeover.
        ssh_source = authorized_ssh_source(info)
        write_config(info, ssh_source)

        # Validate shell syntax before the one operation that can cut networking.
        sh(["/bin/bash", "-n", str(ROOT / "scripts" / "network_lock.sh")])
        sh(["/bin/bash", "-n", str(ROOT / "scripts" / "network_unlock.sh")])
        arm_network_lock(
            ssh_source, info["interface"], info.get("gateway", ""), info.get("network_service", ""),
            info.get("local_ip", ""), info.get("netmask", ""),
        )
        # Containment is armed, but Mac Brain stays OFF until the user explicitly
        # starts it (see LIFECYCLE.md). set_mission_active(True) without user
        # authorization is refused by design, so never claim the mission is active here.
        unload_agent()
        armed = True
        # Do not keep an administrator sudo timestamp alive for the interactive console.
        keepalive.set()

        print("\nNetwork containment is active and verified. Mac Brain is installed and OFF.")
        print("To start the SPEED UP MAC BRAIN mission now, type the start code word below.")
        print("(Anything else leaves it OFF; you can start it later with: macbrain start)")
        subprocess.run([info["python"], "-m", "macbrain", "start"], cwd=str(ROOT))
        console = subprocess.run([info["python"], "-m", "macbrain", "console"], cwd=str(ROOT))
        if console.returncode != 0:
            print("Mac Brain console exited with an error. Reconnect later with: macbrain console")
            return console.returncode
        return 0
    finally:
        if not armed:
            unload_agent()
        keepalive.set()


if __name__ == "__main__":
    raise SystemExit(main())
