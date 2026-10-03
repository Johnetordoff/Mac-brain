#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import py_compile
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
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
REQUIRED_PYTHON = (3, 14)


def require_python_baseline() -> None:
    if sys.version_info[:2] != REQUIRED_PYTHON:
        found = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(
            "Mac Brain stops before installation because its repository policy requires "
            f"CPython 3.14.x and this interpreter is {found}. Install the current CPython "
            "3.14 release, make `python3` resolve to it for this install, and rerun "
            "`python3 install.py`. No Mac Brain setup or containment was changed."
        )


def sh(args, *, check=True, capture=False, cwd=None, input_text=None, env=None):
    result = subprocess.run(
        args,
        check=False,
        text=True,
        input=input_text,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise RuntimeError(f"command failed ({result.returncode}): {args!r}\n{detail}")
    return result


def network_service_for_interface(interface: str) -> str:
    result = sh(["/usr/sbin/networksetup", "-listnetworkserviceorder"], check=False, capture=True)
    current = ""
    for raw in (result.stdout or "").splitlines():
        line = raw.strip()
        if line.startswith("(") and ") " in line and "Hardware Port:" not in line:
            current = line.split(") ", 1)[1].strip().lstrip("*").strip()
        if f"Device: {interface})" in line and current:
            return current
    return ""


def sudo_auth() -> threading.Event:
    print("Administrator authentication is required. macOS sudo will ask for your password now.")
    print("Mac Brain does not read, echo, store, or pass your password to the local model.")
    if subprocess.run(["sudo", "-v"]).returncode != 0:
        raise SystemExit("sudo authentication failed")
    stop = threading.Event()

    def keepalive() -> None:
        while not stop.wait(50):
            subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    threading.Thread(target=keepalive, daemon=True).start()
    return stop


def preflight(allow_sip_disabled: bool) -> dict:
    require_python_baseline()
    if platform.system() != "Darwin":
        raise SystemExit("Mac Brain bootstrap must be run on macOS.")
    ver = platform.mac_ver()[0]
    arch = platform.machine()
    print(f"Detected macOS {ver or 'unknown'} on {arch}; CPython {platform.python_version()}.")
    if arch != "x86_64":
        raise SystemExit("This Mac Brain build is intentionally targeted at Intel x86_64.")
    if ver and not ver.startswith("11.7."):
        print("WARNING: primary target remains Big Sur 11.7.x.")
    if not Path("/usr/bin/git").exists():
        raise SystemExit("/usr/bin/git is missing. Apple Command Line Tools are required.")

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
            raise SystemExit("MACBRAIN_CONTROLLER_IP is not valid IPv4. Containment was NOT applied.")
    if not candidate:
        print("Enter the IPv4 address of the ONE controller computer allowed to initiate SSH after takeover.")
        try:
            candidate = str(ipaddress.IPv4Address(input_fn("Controller computer IPv4 address: ").strip()))
        except ipaddress.AddressValueError:
            raise SystemExit("Controller address is not valid IPv4. Containment was NOT applied.")
    cidr = str(info.get("lan_cidr", ""))
    if cidr and ipaddress.IPv4Address(candidate) not in ipaddress.IPv4Network(cidr, strict=False):
        raise SystemExit(
            f"Controller {candidate} is not on Mac Brain's directly attached LAN {cidr}. "
            "Containment requires same-LAN IPv4 SSH."
        )
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
        blockers.append("Mac is running on battery power; plug in AC before long bootstrap work")
    elif battery_source and battery_source.lower() not in ("ac power", "unknown"):
        warnings.append(f"power source could not be confirmed as AC ({battery_source})")
    if cpu_count and load1 / max(cpu_count, 1) > 1.0:
        warnings.append("the machine is already heavily loaded")
    return {"blockers": blockers, "warnings": warnings}


def early_viability_diagnostics(info: dict) -> None:
    print("\nRunning early Mac Brain viability diagnostics before downloads/builds...")
    cpu = sh(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], check=False, capture=True).stdout.strip()
    count_raw = sh(["/usr/sbin/sysctl", "-n", "hw.logicalcpu"], check=False, capture=True).stdout.strip()
    try:
        cpu_count = int(count_raw)
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
        raise SystemExit(
            "Mac Brain preflight stopped before large downloads/builds: "
            + "; ".join(assessment["blockers"])
            + ". Networking is still normal and containment was not applied."
        )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_ssl_context():
    """Build a verified TLS context, adding macOS system roots when Python cannot see Keychain trust."""
    context = ssl.create_default_context()
    if platform.system() != "Darwin":
        return context

    roots = sh(
        [
            "/usr/bin/security", "find-certificate", "-a", "-p",
            "/System/Library/Keychains/SystemRootCertificates.keychain",
        ],
        check=False, capture=True,
    )
    pem = roots.stdout or ""
    if roots.returncode == 0 and "-----BEGIN CERTIFICATE-----" in pem:
        context.load_verify_locations(cadata=pem)
        print("HTTPS trust: loaded macOS SystemRootCertificates into Python TLS context.")
    else:
        print("WARNING: could not import macOS system root certificates; using Python's default CA store.")
    return context


def download(url: str, dest: Path) -> None:
    """Standard-library resumable HTTPS download with certificate verification."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    context = download_ssl_context()
    for attempt in range(5):
        existing = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "MacBrain/0.7"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                status = getattr(response, "status", 200)
                if existing and status != 206:
                    part.unlink(missing_ok=True)
                    existing = 0
                mode = "ab" if existing else "wb"
                with part.open(mode) as fh:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
            part.replace(dest)
            return
        except (OSError, urllib.error.URLError) as exc:
            if attempt == 4:
                raise SystemExit(f"Download failed after retries: {exc}")
            time.sleep(2)


def verify_command_line_tools() -> None:
    xcode = sh(["/usr/bin/xcode-select", "-p"], check=False, capture=True)
    developer_dir = (xcode.stdout or "").strip()
    if xcode.returncode != 0 or not developer_dir:
        raise SystemExit("Apple Command Line Tools are required before Mac Brain installation.")
    for exe in ("/usr/bin/git", "/usr/bin/make", "/usr/bin/cc", "/usr/bin/c++"):
        if not Path(exe).exists():
            raise SystemExit(f"Required macOS tool missing: {exe}")
    compiler = sh(["/usr/bin/cc", "--version"], check=False, capture=True)
    if compiler.returncode != 0:
        raise SystemExit("Apple clang is not runnable.")
    print(f"Apple Command Line Tools: {developer_dir}")


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
    if cli.exists() and sh([str(cli), "--version"], check=False, capture=True).returncode == 0:
        print("llama-cli already installed and runnable.")
        return
    cli.unlink(missing_ok=True)
    src = VENDOR / "llama.cpp"
    VENDOR.mkdir(parents=True, exist_ok=True)
    if src.exists() and not llama_checkout_matches(src):
        print(f"Replacing stale/incomplete llama.cpp checkout with pinned {LLAMA_TAG}...")
        shutil.rmtree(src, ignore_errors=True)
    if not src.exists():
        print(f"Cloning pinned local inference runtime {LLAMA_TAG} before containment...")
        sh(["/usr/bin/git", "clone", "--depth", "1", "--branch", LLAMA_TAG, LLAMA_REPO, str(src)])
    if not llama_checkout_matches(src):
        raise SystemExit(
            f"llama.cpp checkout is not the expected pinned revision {LLAMA_COMMIT}. "
            "Networking is still normal; rerun python3.14 install.py to retry."
        )
    env = os.environ.copy()
    env.update({"LLAMA_MAKEFILE": "1", "GGML_NO_METAL": "1", "GGML_NO_OPENMP": "1"})
    result = sh(["/usr/bin/make", "-j2", "llama-cli"], check=False, cwd=src, env=env)
    if result.returncode != 0:
        raise SystemExit(
            f"llama.cpp {LLAMA_TAG} build failed. Networking is still normal; "
            "review the compiler/linker output above."
        )
    built = src / "llama-cli"
    if not built.exists():
        raise SystemExit("Inference build completed but llama-cli was not found.")
    shutil.copy2(built, cli)
    os.chmod(cli, 0o755)


def install_model() -> None:
    if MODEL.exists() and sha256(MODEL) == MODEL_SHA256:
        print("Local model already present and verified.")
        return
    MODEL.unlink(missing_ok=True)
    print("Downloading local Qwen model before containment...")
    download(MODEL_URL, MODEL)
    actual = sha256(MODEL)
    if actual != MODEL_SHA256:
        MODEL.unlink(missing_ok=True)
        raise SystemExit(f"Model checksum mismatch: got {actual}")


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
        "git_repos_dir": str(APP / "git"),
        "python_series": "3.14",
    }
    (APP / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(APP / "config.json", 0o600)
    (APP / "mission.active").unlink(missing_ok=True)
    network = {
        "gateway_before_isolation": info.get("gateway", ""),
        "interface": info.get("interface", "en0"),
        "authorized_ssh_source": ssh_source,
        "network_service": info.get("network_service", ""),
    }
    (APP / "install-network.json").write_text(json.dumps(network, indent=2) + "\n", encoding="utf-8")
    os.chmod(APP / "install-network.json", 0o600)


def write_launch_agent(info: dict) -> Path:
    src = (ROOT / "launchd" / "com.macbrain.performancehunter.plist.template").read_text(encoding="utf-8")
    src = src.replace("__PYTHON__", info["python"]).replace("__REPO__", str(ROOT)).replace("__HOME__", str(HOME))
    agents = HOME / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    dest = agents / "com.macbrain.performancehunter.plist"
    dest.write_text(src, encoding="utf-8")
    sh(["/bin/launchctl", "unload", str(dest)], check=False)
    return dest


def proof_of_life(timeout: float = 120.0) -> None:
    from macbrain import db
    from macbrain.lifecycle import CONTAINMENT_MARKER, launch_worker
    if CONTAINMENT_MARKER.exists():
        print("Containment is already armed; worker verification waits for explicit start.")
        return
    started = time.time()
    if not launch_worker():
        raise SystemExit("Background worker did not start. Containment was NOT applied.")
    while time.time() - started < timeout:
        recent = db.recent_samples(1)
        if recent and float(recent[0].get("ts", 0)) >= started:
            print("Performance Hunter background worker is recording evidence.")
            return
        time.sleep(2)
    raise SystemExit("Background worker recorded no fresh evidence. Containment was NOT applied.")


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
    sh(["sudo", "-n", "/usr/sbin/systemsetup", "-setremotelogin", "on"], check=False)
    time.sleep(1)
    if not _ssh_listening():
        sh(["sudo", "-n", "/bin/launchctl", "load", "-w", "/System/Library/LaunchDaemons/ssh.plist"], check=False)
        time.sleep(1)
    if not _ssh_listening():
        raise SystemExit("SSH is not listening on port 22. Enable Remote Login and rerun install.py.")


def arm_network_lock(ssh_source: str, interface: str, gateway: str, network_service: str, local_ip: str, netmask: str) -> None:
    print("\nThe next step applies the low-level inbound-only containment boundary.")
    print(f"Controller allowed to initiate SSH: {ssh_source}")
    phrase = input("Type ARM MAC BRAIN to apply network containment: ").strip()
    if phrase != "ARM MAC BRAIN":
        raise SystemExit("Mac Brain was not armed. Networking remains normal and Mac Brain is OFF.")
    if not all((gateway, network_service, local_ip, netmask)):
        raise SystemExit("Active IPv4 service is incomplete; refusing takeover.")
    cmd = [
        "sudo", "-n", str(Path(sys.executable).resolve()), str(ROOT / "scripts" / "network_lock.py"),
        "--source", ssh_source,
        "--interface", interface,
        "--gateway", gateway,
        "--service", network_service,
        "--ip", local_ip,
        "--netmask", netmask,
    ]
    sh(cmd)


def run_repo_self_test(info: dict) -> None:
    print("Running repository policy and self-tests before installation...")
    policy = subprocess.run(
        [info["python"], str(ROOT / "tools" / "repo_policy.py")],
        cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
    )
    if policy.returncode != 0:
        print(policy.stdout or "")
        raise SystemExit("Mac Brain repository policy failed. Nothing has been isolated.")
    env = os.environ.copy()
    env["MACBRAIN_HOME"] = str(APP / "selftest-state")
    tests = subprocess.run(
        [info["python"], "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=str(ROOT), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
    )
    if tests.returncode != 0:
        print(tests.stdout or "")
        raise SystemExit("Mac Brain self-tests failed. Nothing has been isolated.")
    shutil.rmtree(APP / "selftest-state", ignore_errors=True)


def runtime_smoke_test(info: dict) -> None:
    from macbrain.llm import llama_cli_args
    cli = RUNTIME / "llama-cli"
    prompt = "<|im_start|>system\nAnswer with exactly: MAC BRAIN AWAKE<|im_end|>\n<|im_start|>user\nWake up.<|im_end|>\n<|im_start|>assistant\n"
    cmd = llama_cli_args(cli, MODEL, prompt, threads=2, context=512, predict=12, temp="0")
    try:
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=420, check=False)
    except subprocess.TimeoutExpired:
        raise SystemExit("Local-model smoke test timed out. Containment was NOT applied.")
    if result.returncode != 0 or "MAC BRAIN" not in (result.stdout or "").upper():
        raise SystemExit("Local-model smoke test failed. Containment was NOT applied.")


def install_command_wrapper(info: dict) -> None:
    wrapper = APP / "macbrain-wrapper.py"
    python = str(Path(info["python"]).resolve())
    wrapper.write_text(
        f"#!{python}\n"
        "from __future__ import annotations\n"
        "import os\n"
        "import sys\n"
        f"ROOT = {str(ROOT)!r}\n"
        "os.chdir(ROOT)\n"
        "sys.path.insert(0, ROOT)\n"
        "from macbrain.__main__ import main\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    os.chmod(wrapper, 0o755)
    target = Path("/usr/local/bin/macbrain")
    sh(["sudo", "-n", "/bin/mkdir", "-p", "/usr/local/bin"])
    sh(["sudo", "-n", "/bin/cp", str(wrapper), str(target)])
    sh(["sudo", "-n", "/usr/sbin/chown", "root:wheel", str(target)])
    sh(["sudo", "-n", "/bin/chmod", "755", str(target)])


def validate_python_programs() -> None:
    for path in [ROOT / "install.py", *sorted((ROOT / "macbrain").glob("*.py")), *sorted((ROOT / "scripts").glob("*.py")), *sorted((ROOT / "tools").glob("*.py"))]:
        py_compile.compile(str(path), doraise=True)


def enable_wake_for_network() -> None:
    sh(["sudo", "-n", "/usr/bin/pmset", "-a", "womp", "1"], check=False)


def unload_agent() -> None:
    dest = HOME / "Library" / "LaunchAgents" / "com.macbrain.performancehunter.plist"
    # Best-effort cleanup. Big Sur's legacy launchctl prints "Unload failed: 5"
    # when the job is already absent/not loaded; capture it so a non-fatal cleanup
    # does not look like the installation failure that triggered this finally block.
    sh(["/bin/launchctl", "unload", str(dest)], check=False, capture=True)


def main() -> int:
    require_python_baseline()
    parser = argparse.ArgumentParser(description="Install Speed Up Mac Brain on the old Mac.")
    parser.add_argument("--allow-sip-disabled", action="store_true")
    args = parser.parse_args()

    keepalive = sudo_auth()
    armed = False
    try:
        info = preflight(args.allow_sip_disabled)
        APP.mkdir(parents=True, exist_ok=True)
        (APP / "quarantine").mkdir(exist_ok=True)
        (APP / "git").mkdir(exist_ok=True)

        validate_python_programs()
        verify_command_line_tools()
        run_repo_self_test(info)
        early_viability_diagnostics(info)
        build_runtime()
        install_model()
        write_config(info, "")
        install_command_wrapper(info)
        ensure_ssh()
        enable_wake_for_network()
        write_launch_agent(info)
        runtime_smoke_test(info)

        sh([info["python"], "-m", "macbrain", "first-mission", "--no-llm"], cwd=ROOT)
        proof_of_life()
        doctor = sh([info["python"], "-m", "macbrain", "doctor", "--expect-running"], check=False, capture=True, cwd=ROOT)
        print((doctor.stdout or "").strip())
        if doctor.returncode != 0:
            raise SystemExit("Background proof-of-life failed. Containment was NOT applied.")
        unload_agent()

        demo = subprocess.run([info["python"], "-m", "macbrain", "prearm-console"], cwd=str(ROOT))
        if demo.returncode != 0:
            raise SystemExit("Takeover was not approved. Networking remains normal.")

        ssh_source = authorized_ssh_source(info)
        write_config(info, ssh_source)
        validate_python_programs()
        arm_network_lock(
            ssh_source,
            info["interface"],
            info.get("gateway", ""),
            info.get("network_service", ""),
            info.get("local_ip", ""),
            info.get("netmask", ""),
        )
        unload_agent()
        armed = True
        keepalive.set()

        print("\nNetwork containment is active and verified. Mac Brain is installed and OFF.")
        subprocess.run([info["python"], "-m", "macbrain", "start"], cwd=str(ROOT))
        console = subprocess.run([info["python"], "-m", "macbrain", "console"], cwd=str(ROOT))
        return console.returncode
    finally:
        if not armed:
            unload_agent()
        keepalive.set()


if __name__ == "__main__":
    raise SystemExit(main())
