#!/usr/bin/env python3
"""open Archive (.oa) interpreter/compiler.

Usage:
  python oa.py program.oa              # compile to a standalone script, then self-delete
  python oa.py --run program.oa        # interpret directly
  python oa.py --no-self-delete program.oa
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


NO_ARG_COMMANDS = {
    "open google account",
    "open py",
    "terminal clear",
    "sys info",
    "net myip",
    "web speedtest",
    "android torch on",
    "android torch off",
    "sys reboot",
    "sys shutdown",
    "proc list",
    "time show",
    "exit",
}

ARG_COMMANDS = {
    "net ping",
    "file create",
    "dir make",
    "web open",
    "proc kill",
    "delay",
    "notify",
    "print",
    "file delete",
    "file write",
    "file read",
    "dir delete",
    "dir list",
    "var set",
    "var print",
    "net download",
    "web search",
    "web portcheck",
    "android vibrate",
    "android toast",
    "android clip set",
    "android tts",
    "proc run",
    "terminal title",
    "terminal color",
    "if fileexists",
    "goto",
    "label",
    "math add",
    "open cod",
}

COMMANDS = NO_ARG_COMMANDS | ARG_COMMANDS
PREFIX_COMMANDS = sorted(COMMANDS, key=len, reverse=True)
COLORS = {"red": "31", "green": "32", "yellow": "33", "blue": "34", "reset": "0"}


@dataclass(frozen=True)
class Instruction:
    line_no: int
    command: str
    arg: str = ""
    source: Path | None = None


def command_pattern(command: str) -> re.Pattern[str]:
    """Build a case-insensitive matcher that tolerates repeated whitespace."""
    words = [re.escape(part) for part in command.split()]
    return re.compile(r"^" + r"\s+".join(words) + r"(?:\s+(?P<arg>.*))?$", re.IGNORECASE)


COMMAND_PATTERNS = [(command, command_pattern(command)) for command in PREFIX_COMMANDS]


def parse_oa(source: Path, seen: set[Path] | None = None) -> list[Instruction]:
    source = source.expanduser().resolve()
    if source.suffix.lower() != ".oa":
        raise ValueError("open Archive source files must use the .oa extension")
    seen = set() if seen is None else seen
    if source in seen:
        raise ValueError(f"Recursive Open Cod include detected: {source}")
    seen.add(source)

    instructions: list[Instruction] = []
    for line_no, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        matched = ""
        arg = ""
        for command, pattern in COMMAND_PATTERNS:
            match = pattern.match(stripped)
            if not match:
                continue
            candidate_arg = (match.group("arg") or "").strip()
            if command in NO_ARG_COMMANDS and candidate_arg:
                continue
            matched = command
            arg = candidate_arg
            break
        if not matched:
            raise ValueError(f"{source}:{line_no}: unknown .oa command: {stripped}")
        if matched in ARG_COMMANDS and not arg:
            raise ValueError(f"{source}:{line_no}: command '{matched}' requires an argument")
        if matched == "open cod":
            include = (source.parent / arg).expanduser().resolve()
            instructions.extend(parse_oa(include, seen))
        else:
            instructions.append(Instruction(line_no, matched, arg, source))
    seen.remove(source)
    return instructions

def split_pair(arg: str, sep: str, command: str) -> tuple[str, str]:
    if sep not in arg:
        raise ValueError(f"{command} expects '{sep}' in its argument")
    left, right = arg.split(sep, 1)
    left, right = left.strip(), right.strip()
    if not left or not right:
        raise ValueError(f"{command} expects values on both sides of '{sep}'")
    return left, right


def parse_port(arg: str) -> tuple[str, int]:
    host, port = split_pair(arg, ":", "web portcheck")
    return host, int(port)


def build_labels(items: list[Instruction]) -> dict[str, int]:
    return {item.arg.lower(): idx for idx, item in enumerate(items) if item.command == "label"}


def interpret(source: Path) -> None:
    items = parse_oa(source)
    labels = build_labels(items)
    variables: dict[str, str] = {}
    pc = 0
    while pc < len(items):
        jump_to = run_instruction(items[pc], variables, labels)
        pc = jump_to if jump_to is not None else pc + 1


def run_instruction(item: Instruction, variables: dict[str, str], labels: dict[str, int]) -> int | None:
    cmd, arg = item.command, item.arg
    if cmd == "label":
        return None
    if cmd == "goto":
        return labels[arg.lower()]
    if cmd == "if fileexists":
        path, label = parse_if_fileexists(arg)
        return labels[label.lower()] if Path(path).exists() else None
    if cmd == "exit":
        raise SystemExit(0)
    if cmd == "print":
        print(arg)
    elif cmd == "delay":
        time.sleep(float(arg))
    elif cmd == "terminal clear":
        os.system("cls" if os.name == "nt" else "clear")
    elif cmd == "terminal title":
        set_terminal_title(arg)
    elif cmd == "terminal color":
        set_terminal_color(arg)
    elif cmd == "file create":
        path = Path(arg)
        path.parent.mkdir(parents=True, exist_ok=True) if path.parent != Path(".") else None
        path.touch(exist_ok=True)
    elif cmd == "file delete":
        Path(arg).unlink(missing_ok=True)
    elif cmd == "file write":
        path, text = split_pair(arg, ">>", "file write")
        Path(path).parent.mkdir(parents=True, exist_ok=True) if Path(path).parent != Path(".") else None
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    elif cmd == "file read":
        print(Path(arg).read_text(encoding="utf-8"), end="")
    elif cmd == "dir make":
        Path(arg).mkdir(parents=True, exist_ok=True)
    elif cmd == "dir delete":
        shutil.rmtree(arg, ignore_errors=True)
    elif cmd == "dir list":
        for child in sorted(Path(arg).iterdir()):
            print(child.name)
    elif cmd == "var set":
        name, value = split_pair(arg, "=", "var set")
        variables[name] = value
    elif cmd == "var print":
        print(variables.get(arg, ""))
    elif cmd == "math add":
        name, number = split_pair(arg, ">", "math add")
        variables[name] = str(float(variables.get(name, "0")) + float(number))
    elif cmd == "web open":
        webbrowser.open(arg)
    elif cmd == "web search":
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(arg))
    elif cmd == "web portcheck":
        host, port = parse_port(arg)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            print(f"Port {host}:{port}: {'OPEN' if sock.connect_ex((host, port)) == 0 else 'CLOSED'}")
    elif cmd == "web speedtest":
        speedtest_python()
    elif cmd == "net ping":
        flag = "-n" if os.name == "nt" else "-c"
        result = subprocess.run(["ping", flag, "1", arg], check=False)
        print(f"Ping {arg}: {'OK' if result.returncode == 0 else 'FAILED'}")
    elif cmd == "net download":
        url, target = split_pair(arg, ">>", "net download")
        Path(target).parent.mkdir(parents=True, exist_ok=True) if Path(target).parent != Path(".") else None
        urllib.request.urlretrieve(url, target)
    elif cmd == "net myip":
        print(urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode("utf-8"))
    elif cmd == "proc kill":
        subprocess.run(["taskkill", "/F", "/IM", arg] if os.name == "nt" else ["pkill", "-f", arg], check=False)
    elif cmd == "proc list":
        subprocess.run(["tasklist"] if os.name == "nt" else ["ps", "aux"], check=False)
    elif cmd == "proc run":
        subprocess.Popen(arg if os.name == "nt" else ["sh", "-c", arg], shell=(os.name == "nt"))
    elif cmd == "sys info":
        print_system_info()
    elif cmd == "sys reboot":
        print("open Archive warning: reboot requested.")
        subprocess.run(["shutdown", "/r", "/t", "5"] if os.name == "nt" else ["sudo", "shutdown", "-r", "+1"], check=False)
    elif cmd == "sys shutdown":
        print("open Archive warning: shutdown requested.")
        subprocess.run(["shutdown", "/s", "/t", "5"] if os.name == "nt" else ["sudo", "shutdown", "-h", "+1"], check=False)
    elif cmd == "time show":
        print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    elif cmd == "notify":
        notify(arg)
    elif cmd == "open google account":
        webbrowser.open("https://accounts.google.com/AccountChooser")
        print("Opened Google account chooser in the default browser.")
    elif cmd == "open py":
        ensure_python()
    elif cmd.startswith("android "):
        run_android_command(cmd, arg)
    else:
        raise RuntimeError(f"Unsupported command at line {item.line_no}: {cmd}")
    return None


def parse_if_fileexists(arg: str) -> tuple[str, str]:
    match = re.match(r"^(?P<path>.+?)\s+goto\s+(?P<label>\S+)\s*$", arg, re.IGNORECASE)
    if not match:
        raise ValueError("if fileexists expects: If FileExists [path] Goto [label]")
    return match.group("path").strip(), match.group("label").strip()


def print_system_info() -> None:
    print(f"OS: {platform.platform()}")
    print(f"CPU: {platform.processor() or platform.machine()}")
    if importlib.util.find_spec("psutil") is None:
        print("RAM/Battery: install psutil for detailed values")
        return
    psutil = importlib.import_module("psutil")
    print(f"RAM: {round(psutil.virtual_memory().total / (1024**3), 2)} GB")
    battery = psutil.sensors_battery()
    print("Battery: unavailable" if battery is None else f"Battery: {battery.percent}%")


def notify(text: str) -> None:
    system = platform.system().lower()
    if system == "darwin":
        subprocess.run(["osascript", "-e", f'display notification {text!r} with title "open Archive"'], check=False)
    elif system == "windows":
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show({text!r}, 'open Archive')"], check=False)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "open Archive", text], check=False)
    else:
        print(f"[notification] {text}")


def ensure_python() -> None:
    if shutil.which("python3") or shutil.which("python"):
        print("Python is already installed.")
        return
    system = platform.system().lower()
    print("Python was not found; attempting installation with the system package manager.")
    if system == "linux":
        if shutil.which("pkg"):
            subprocess.run(["pkg", "install", "-y", "python"], check=False)
        elif shutil.which("apt-get"):
            subprocess.run(["sudo", "apt-get", "update"], check=False)
            subprocess.run(["sudo", "apt-get", "install", "-y", "python3"], check=False)
        elif shutil.which("dnf"):
            subprocess.run(["sudo", "dnf", "install", "-y", "python3"], check=False)
        elif shutil.which("pacman"):
            subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm", "python"], check=False)
    elif system == "darwin" and shutil.which("brew"):
        subprocess.run(["brew", "install", "python"], check=False)
    elif system == "windows":
        subprocess.run(["winget", "install", "-e", "--id", "Python.Python.3.12"], check=False)
    else:
        print("Automatic Python installation is not supported on this system.")


def run_android_command(cmd: str, arg: str) -> None:
    termux = shutil.which("termux-vibrate") or shutil.which("termux-toast") or shutil.which("termux-torch")
    if termux:
        if cmd == "android vibrate":
            subprocess.run(["termux-vibrate", "-d", arg], check=False)
        elif cmd == "android toast":
            subprocess.run(["termux-toast", arg], check=False)
        elif cmd == "android torch on":
            subprocess.run(["termux-torch", "on"], check=False)
        elif cmd == "android torch off":
            subprocess.run(["termux-torch", "off"], check=False)
        elif cmd == "android clip set":
            subprocess.run(["termux-clipboard-set", arg], check=False)
        elif cmd == "android tts":
            subprocess.run(["termux-tts-speak", arg], check=False)
        return
    if cmd == "android clip set":
        set_clipboard(arg)
    elif cmd == "android tts":
        speak_text(arg)
    else:
        print(f"[android simulation] {cmd} {arg}".strip())


def set_clipboard(text: str) -> None:
    if platform.system().lower() == "darwin" and shutil.which("pbcopy"):
        subprocess.run("pbcopy", input=text, text=True, check=False)
    elif os.name == "nt":
        subprocess.run("clip", input=text, text=True, shell=True, check=False)
    elif shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=False)
    elif shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text, text=True, check=False)
    else:
        print(f"[clipboard simulation] {text}")


def speak_text(text: str) -> None:
    if platform.system().lower() == "darwin":
        subprocess.run(["say", text], check=False)
    elif os.name == "nt":
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak({text!r})"], check=False)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", text], check=False)
    else:
        print(f"[tts simulation] {text}")


def set_terminal_title(text: str) -> None:
    if os.name == "nt":
        os.system(f"title {text}")
    else:
        print(f"\033]0;{text}\007", end="")


def set_terminal_color(color: str) -> None:
    code = COLORS.get(color.lower())
    if not code:
        print(f"Unknown color '{color}'. Supported: Red, Green, Yellow, Blue, Reset")
        return
    if os.name == "nt":
        print(f"[terminal color] {color}")
    else:
        print(f"\033[{code}m", end="")


def speedtest_python() -> None:
    start = time.time()
    size = len(urllib.request.urlopen("https://speed.cloudflare.com/__down?bytes=1000000", timeout=20).read())
    elapsed = max(time.time() - start, 0.001)
    print(f"Download speed sample: {(size * 8 / elapsed / 1_000_000):.2f} Mbps")


def compile_to_script(source: Path, output: Path | None = None) -> Path:
    instructions = parse_oa(source)
    target = output or source.with_suffix(".cmd" if os.name == "nt" else ".sh")
    body = compile_windows(instructions) if os.name == "nt" else compile_posix(instructions)
    target.write_text(body, encoding="utf-8", newline="\n")
    if os.name != "nt":
        target.chmod(target.stat().st_mode | 0o755)
    return target


def q_posix(value: str) -> str:
    import shlex
    return shlex.quote(value)


def shell_var(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return f"OA_{safe}"


def compile_posix(items: list[Instruction]) -> str:
    lines = ["#!/usr/bin/env bash", "set -u", ""]
    for item in items:
        c, a = item.command, item.arg
        lines.append(f"# .oa line {item.line_no}: {c}")
        if c == "label":
            lines.append(f": oa_label_{shell_var(a)}")
        elif c == "goto":
            lines.append(f"goto_target={q_posix(': oa_label_' + shell_var(a))}; exec \"${{OA_SELF_ORIGINAL:-$0}}\" --oa-goto \"$goto_target\"")
        elif c == "if fileexists":
            path, label = parse_if_fileexists(a)
            lines.append(f"[ -e {q_posix(path)} ] && goto_target={q_posix(': oa_label_' + shell_var(label))} && exec \"${{OA_SELF_ORIGINAL:-$0}}\" --oa-goto \"$goto_target\"")
        elif c == "print":
            lines.append(f"printf '%s\\n' {q_posix(a)}")
        elif c == "delay":
            lines.append(f"sleep {q_posix(a)}")
        elif c == "terminal clear":
            lines.append("clear")
        elif c == "terminal title":
            lines.append(f"printf '\\033]0;%s\\007' {q_posix(a)}")
        elif c == "terminal color":
            lines.append(f"case {q_posix(a.lower())} in red) printf '\\033[31m';; green) printf '\\033[32m';; yellow) printf '\\033[33m';; blue) printf '\\033[34m';; reset) printf '\\033[0m';; esac")
        elif c == "file create":
            lines.append(f"mkdir -p -- \"$(dirname -- {q_posix(a)})\"; touch -- {q_posix(a)}")
        elif c == "file delete":
            lines.append(f"rm -f -- {q_posix(a)}")
        elif c == "file write":
            path, text = split_pair(a, ">>", "file write")
            lines.append(f"mkdir -p -- \"$(dirname -- {q_posix(path)})\"; printf '%s\\n' {q_posix(text)} >> {q_posix(path)}")
        elif c == "file read":
            lines.append(f"cat -- {q_posix(a)}")
        elif c == "dir make":
            lines.append(f"mkdir -p -- {q_posix(a)}")
        elif c == "dir delete":
            lines.append(f"rm -rf -- {q_posix(a)}")
        elif c == "dir list":
            lines.append(f"find {q_posix(a)} -maxdepth 1 -mindepth 1 -printf '%f\\n' 2>/dev/null || ls -A {q_posix(a)}")
        elif c == "var set":
            name, value = split_pair(a, "=", "var set")
            lines.append(f"export {shell_var(name)}={q_posix(value)}")
        elif c == "var print":
            lines.append(f"printf '%s\\n' \"${{{shell_var(a)}:-}}\"")
        elif c == "math add":
            name, number = split_pair(a, ">", "math add")
            var = shell_var(name)
            lines.append(f"export {var}=$(awk 'BEGIN {{ print (ENVIRON[\"{var}\"]+0)+({q_posix(number)}) }}')")
        elif c == "web open":
            lines.append(f"(xdg-open {q_posix(a)} || termux-open-url {q_posix(a)} || open {q_posix(a)}) >/dev/null 2>&1 &")
        elif c == "web search":
            url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(a)
            lines.append(f"(xdg-open {q_posix(url)} || termux-open-url {q_posix(url)} || open {q_posix(url)}) >/dev/null 2>&1 &")
        elif c == "web portcheck":
            host, port = parse_port(a)
            lines.append(f"(nc -z -w 5 {q_posix(host)} {port} >/dev/null 2>&1 || timeout 5 bash -c '</dev/tcp/{host}/{port}' >/dev/null 2>&1) && echo 'Port {host}:{port}: OPEN' || echo 'Port {host}:{port}: CLOSED'")
        elif c == "web speedtest":
            lines.append("curl -L --max-time 20 -o /dev/null -w 'Download speed sample: %{speed_download} bytes/s\\n' 'https://speed.cloudflare.com/__down?bytes=1000000'")
        elif c == "net ping":
            lines.append(f"ping -c 1 -- {q_posix(a)} >/dev/null && echo 'Ping {a}: OK' || echo 'Ping {a}: FAILED'")
        elif c == "net download":
            url, target = split_pair(a, ">>", "net download")
            lines.append(f"mkdir -p -- \"$(dirname -- {q_posix(target)})\"; (curl -L {q_posix(url)} -o {q_posix(target)} || wget -O {q_posix(target)} {q_posix(url)})")
        elif c == "net myip":
            lines.append("curl -s https://api.ipify.org || wget -qO- https://api.ipify.org; printf '\\n'")
        elif c == "proc kill":
            lines.append(f"pkill -f -- {q_posix(a)} || true")
        elif c == "proc list":
            lines.append("ps aux")
        elif c == "proc run":
            lines.append(f"nohup sh -c {q_posix(a)} >/dev/null 2>&1 &")
        elif c == "sys info":
            lines += ["uname -a", "printf 'CPU: '; (sysctl -n machdep.cpu.brand_string 2>/dev/null || lscpu | sed -n 's/^Model name:[[:space:]]*//p' | head -1 || uname -m)", "printf 'RAM: '; (free -h | awk '/Mem:/ {print $2}' || sysctl -n hw.memsize)", "printf 'Battery: '; (termux-battery-status 2>/dev/null || acpi -b 2>/dev/null || pmset -g batt 2>/dev/null || echo unavailable)"]
        elif c == "sys reboot":
            lines.append("echo 'open Archive warning: reboot requested.'; (termux-reboot || sudo shutdown -r +1 || reboot) 2>/dev/null")
        elif c == "sys shutdown":
            lines.append("echo 'open Archive warning: shutdown requested.'; (sudo shutdown -h +1 || poweroff) 2>/dev/null")
        elif c == "time show":
            lines.append("date '+%Y-%m-%d %H:%M:%S'")
        elif c == "notify":
            lines.append(f"if command -v termux-notification >/dev/null; then termux-notification --title 'open Archive' --content {q_posix(a)}; elif command -v notify-send >/dev/null; then notify-send 'open Archive' {q_posix(a)}; else echo '[notification] {a}'; fi")
        elif c == "open google account":
            lines.append("(xdg-open 'https://accounts.google.com/AccountChooser' || termux-open-url 'https://accounts.google.com/AccountChooser' || open 'https://accounts.google.com/AccountChooser') >/dev/null 2>&1 &")
        elif c == "open py":
            lines.append("if command -v python3 >/dev/null || command -v python >/dev/null; then echo 'Python is already installed.'; elif command -v pkg >/dev/null; then pkg install -y python; elif command -v apt-get >/dev/null; then sudo apt-get update && sudo apt-get install -y python3; elif command -v dnf >/dev/null; then sudo dnf install -y python3; elif command -v brew >/dev/null; then brew install python; else echo 'Automatic Python installation is not supported.'; fi")
        elif c.startswith("android "):
            lines.append(posix_android_line(c, a))
        elif c == "exit":
            lines.append("exit 0")
        lines.append("")
    return add_posix_goto_prelude("\n".join(lines))


def add_posix_goto_prelude(script: str) -> str:
    # Bash has no native goto. For compiled scripts, --oa-goto replays from a label marker.
    prelude = """#!/usr/bin/env bash
set -u
if [ "${1:-}" = "--oa-goto" ]; then
  target="$2"
  tmp="$(mktemp)"
  awk -v target="$target" 'found {print} $0 == target {found=1}' "$0" > "$tmp"
  shift 2
  OA_SELF_ORIGINAL="$0" bash "$tmp" "$@"
  status=$?
  rm -f "$tmp"
  exit "$status"
fi
"""
    return prelude + "\n".join(script.splitlines()[2:])


def posix_android_line(c: str, a: str) -> str:
    if c == "android vibrate":
        return f"command -v termux-vibrate >/dev/null && termux-vibrate -d {q_posix(a)} || echo '[android simulation] vibrate {a}ms'"
    if c == "android toast":
        return f"command -v termux-toast >/dev/null && termux-toast {q_posix(a)} || echo '[android simulation] toast: {a}'"
    if c == "android torch on":
        return "command -v termux-torch >/dev/null && termux-torch on || echo '[android simulation] torch on'"
    if c == "android torch off":
        return "command -v termux-torch >/dev/null && termux-torch off || echo '[android simulation] torch off'"
    if c == "android clip set":
        return f"if command -v termux-clipboard-set >/dev/null; then termux-clipboard-set {q_posix(a)}; elif command -v xclip >/dev/null; then printf '%s' {q_posix(a)} | xclip -selection clipboard; else echo '[clipboard simulation] {a}'; fi"
    if c == "android tts":
        return f"if command -v termux-tts-speak >/dev/null; then termux-tts-speak {q_posix(a)}; elif command -v espeak >/dev/null; then espeak {q_posix(a)}; else echo '[tts simulation] {a}'; fi"
    return ":"


def compile_windows(items: list[Instruction]) -> str:
    lines = ["@echo off", "setlocal EnableDelayedExpansion", ""]
    for item in items:
        c, a = item.command, item.arg.replace('"', '\\"')
        lines.append(f"REM .oa line {item.line_no}: {c}")
        if c == "label":
            lines.append(f":oa_label_{shell_var(a)}")
        elif c == "goto":
            lines.append(f"goto oa_label_{shell_var(a)}")
        elif c == "if fileexists":
            path, label = parse_if_fileexists(a)
            lines.append(f"if exist \"{path}\" goto oa_label_{shell_var(label)}")
        elif c == "print":
            lines.append(f"echo {a}")
        elif c == "delay":
            lines.append(f"timeout /t {a} /nobreak >nul")
        elif c == "terminal clear":
            lines.append("cls")
        elif c == "terminal title":
            lines.append(f"title {a}")
        elif c == "terminal color":
            lines.append(windows_color_line(a))
        elif c == "file create":
            lines.append(f"type nul > \"{a}\"")
        elif c == "file delete":
            lines.append(f"del /f /q \"{a}\" 2>nul")
        elif c == "file write":
            path, text = split_pair(a, ">>", "file write")
            lines.append(f"echo {text}>>\"{path}\"")
        elif c == "file read":
            lines.append(f"type \"{a}\"")
        elif c == "dir make":
            lines.append(f"mkdir \"{a}\" 2>nul")
        elif c == "dir delete":
            lines.append(f"rmdir /s /q \"{a}\" 2>nul")
        elif c == "dir list":
            lines.append(f"dir /b \"{a}\"")
        elif c == "var set":
            name, value = split_pair(a, "=", "var set")
            lines.append(f"set \"{shell_var(name)}={value}\"")
        elif c == "var print":
            lines.append(f"echo !{shell_var(a)}!")
        elif c == "math add":
            name, number = split_pair(a, ">", "math add")
            lines.append(f"set /a {shell_var(name)}=!{shell_var(name)}!+{number}")
        elif c == "web open":
            lines.append(f"start \"\" \"{a}\"")
        elif c == "web search":
            lines.append(f"start \"\" \"https://www.google.com/search?q={urllib.parse.quote_plus(a)}\"")
        elif c == "web portcheck":
            host, port = parse_port(a)
            lines.append(f"powershell -NoProfile -Command \"$c=New-Object Net.Sockets.TcpClient; try{{$c.Connect('{host}',{port}); 'Port {host}:{port}: OPEN'}}catch{{'Port {host}:{port}: CLOSED'}} finally{{$c.Close()}}\"")
        elif c == "web speedtest":
            lines.append("powershell -NoProfile -Command \"$u='https://speed.cloudflare.com/__down?bytes=1000000'; $t=Measure-Command { Invoke-WebRequest $u -OutFile $env:TEMP\\oa_speed.tmp }; $s=(Get-Item $env:TEMP\\oa_speed.tmp).Length; Remove-Item $env:TEMP\\oa_speed.tmp; 'Download speed sample: {0:N2} Mbps' -f (($s*8)/$t.TotalSeconds/1MB)\"")
        elif c == "net ping":
            lines.append(f"ping -n 1 \"{a}\" >nul && echo Ping {a}: OK || echo Ping {a}: FAILED")
        elif c == "net download":
            url, target = split_pair(a, ">>", "net download")
            lines.append(f"powershell -NoProfile -Command \"Invoke-WebRequest -Uri '{url}' -OutFile '{target}'\"")
        elif c == "net myip":
            lines.append("powershell -NoProfile -Command \"(Invoke-WebRequest -UseBasicParsing https://api.ipify.org).Content\"")
        elif c == "proc kill":
            lines.append(f"taskkill /F /IM \"{a}\"")
        elif c == "proc list":
            lines.append("tasklist")
        elif c == "proc run":
            lines.append(f"start \"\" {a}")
        elif c == "sys info":
            lines += ["systeminfo | findstr /B /C:\"OS Name\" /C:\"OS Version\" /C:\"Processor\" /C:\"Total Physical Memory\"", "WMIC Path Win32_Battery Get EstimatedChargeRemaining 2>nul"]
        elif c == "sys reboot":
            lines.append("echo open Archive warning: reboot requested. & shutdown /r /t 5")
        elif c == "sys shutdown":
            lines.append("echo open Archive warning: shutdown requested. & shutdown /s /t 5")
        elif c == "time show":
            lines.append("echo %DATE% %TIME%")
        elif c == "notify":
            lines.append(f"powershell -NoProfile -Command \"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('{a}','open Archive')\"")
        elif c == "open google account":
            lines.append("start \"\" \"https://accounts.google.com/AccountChooser\"")
        elif c == "open py":
            lines.append("where python >nul 2>nul || winget install -e --id Python.Python.3.12")
        elif c.startswith("android "):
            lines.append(f"echo [android simulation] {c} {a}")
        elif c == "exit":
            lines.append("exit /b 0")
        lines.append("")
    return "\n".join(lines)


def windows_color_line(color: str) -> str:
    return {"red": "color 0C", "green": "color 0A", "yellow": "color 0E", "blue": "color 09", "reset": "color 07"}.get(color.lower(), "color 07")


def schedule_self_delete(script: Path) -> None:
    if not script.exists():
        return
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", f"ping 127.0.0.1 -n 2 > nul & del /f /q \"{script}\""], close_fds=True)
    else:
        subprocess.Popen(["sh", "-c", f"sleep 1; rm -f -- {q_posix(str(script))}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="open Archive (.oa) interpreter/compiler")
    parser.add_argument("source", type=Path, help="Path to a .oa source file")
    parser.add_argument("-o", "--output", type=Path, help="Compiled script path")
    parser.add_argument("--run", action="store_true", help="Interpret directly instead of compiling")
    parser.add_argument("--no-self-delete", action="store_true", help="Keep this compiler after successful compilation")
    args = parser.parse_args(argv)
    if args.run:
        interpret(args.source)
        return 0
    compiled = compile_to_script(args.source, args.output)
    print(f"Compiled {args.source} -> {compiled}")
    if not args.no_self_delete:
        schedule_self_delete(Path(__file__).resolve())
        print("Self-deletion scheduled for the compiler script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

