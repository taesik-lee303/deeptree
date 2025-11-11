#!/usr/bin/env python3
"""Run multiple DeepTree modules together while keeping room for future expansion."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

SRC_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXECUTABLE = sys.executable


@dataclass(frozen=True)
class ModuleSpec:
    target: str
    description: str
    default: bool = False
    extra_args: Sequence[str] = field(default_factory=tuple)


MODULE_REGISTRY: Dict[str, ModuleSpec] = {
    "carecall": ModuleSpec(
        target="modules.carecall.main",
        description="DeepCare conversation system entrypoint",
        default=True,
    ),
    "rppg": ModuleSpec(
        target="modules.rppg.thermal_rppg",
        description="Thermal rPPG pipeline",
        default=True,
    ),
    "display": ModuleSpec(
        target="modules.display.sensor_display",
        description="Sensor display (disabled until ready)",
        default=False,
    ),
    "display-switcher": ModuleSpec(
        target="apps.display_switcher",
        description="Switch sensor display to carecall view when conversation events arrive",
        default=True,
        extra_args=("--idle-timeout", "30", "--enable-uart-producer"),
    ),

}

DEFAULT_MODULES: Tuple[str, ...] = tuple(
    name for name, spec in MODULE_REGISTRY.items() if spec.default
)

def determine_modules(requested: Sequence[str] | None, include_display: bool) -> List[str]:
    if requested:
        modules = list(dict.fromkeys(requested))
    else:
        modules = list(DEFAULT_MODULES)

    if include_display and "display" not in modules:
        modules.append("display")
    if not include_display:
        modules = [name for name in modules if name != "display"]

    return modules


def format_command(cmd: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


async def wait_for_exit(name: str, proc: asyncio.subprocess.Process, stop_event: asyncio.Event) -> None:
    return_code = await proc.wait()
    print(f"[launcher] {name} exited with code {return_code}")
    stop_event.set()


async def terminate_process(name: str, proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return

    print(f"[launcher] terminating {name}")
    try:
        proc.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        print(f"[launcher] killing {name} after timeout")
        proc.kill()
        await proc.wait()


async def run_launcher(modules: Sequence[str], module_args: Dict[str, List[str]]) -> int:
    if not modules:
        print("[launcher] No modules selected to run.")
        return 1

    processes: List[Tuple[str, asyncio.subprocess.Process]] = []
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def handle_signal(signum, frame) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = str(signum)
        print(f"\n[launcher] received {sig_name}, shutting down...")
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, RuntimeError):
            pass

    env = os.environ.copy()
    python_path = env.get("PYTHONPATH")
    src_path = str(SRC_ROOT)
    if python_path:
        env["PYTHONPATH"] = src_path + os.pathsep + python_path
    else:
        env["PYTHONPATH"] = src_path

    env.setdefault("RPPG_DEBUG_VISUAL", "0")

    for name in modules:
        spec = MODULE_REGISTRY[name]
        args = [
            PYTHON_EXECUTABLE,
            "-m",
            spec.target,
            *spec.extra_args,
            *module_args.get(name, []),
        ]
        print(f"[launcher] starting {name}: {format_command(args)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(SRC_ROOT),
                env=env,
            )
        except FileNotFoundError as exc:
            print(f"[launcher] Failed to start {name}: {exc}")
            await stop_event.wait()
            return 1
        processes.append((name, proc))

    watchers = [
        asyncio.create_task(wait_for_exit(name, proc, stop_event))
        for name, proc in processes
    ]

    await stop_event.wait()

    await asyncio.gather(
        *(terminate_process(name, proc) for name, proc in processes),
        return_exceptions=True,
    )
    await asyncio.gather(*watchers, return_exceptions=True)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch multiple DeepTree modules in parallel.",
    )
    parser.add_argument(
        "-m",
        "--module",
        dest="modules",
        action="append",
        choices=tuple(MODULE_REGISTRY.keys()),
        help="Module name to run (repeatable). Defaults to carecall and rppg.",
    )
    parser.add_argument(
        "--include-display",
        action="store_true",
        help="Include the display module once it becomes available.",
    )
    parser.add_argument(
        "--module-arg",
        action="append",
        default=[],
        metavar="NAME=ARG",
        help="Forward an extra argument to a module (repeat per argument).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered modules and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print("Available modules:")
        for name, spec in MODULE_REGISTRY.items():
            flag = "(default)" if spec.default else ""
            print(f"  - {name:8s} {flag:9s} -> python -m {spec.target}\n      {spec.description}")
        return 0

    selected_modules = determine_modules(args.modules, args.include_display)

    module_args: Dict[str, List[str]] = {}
    for raw in args.module_arg:
        if "=" not in raw:
            parser.error("--module-arg expects NAME=ARG format")
        name, value = raw.split("=", 1)
        if name not in MODULE_REGISTRY:
            parser.error(f"Unknown module for --module-arg: {name}")
        module_args.setdefault(name, []).append(value)

    return asyncio.run(run_launcher(selected_modules, module_args))


if __name__ == "__main__":
    sys.exit(main())
