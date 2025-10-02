#!/usr/bin/env python3
"""센서 디스플레이와 케어콜 전용 디스플레이를 상황에 따라 전환하는 런처."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SRC_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXECUTABLE = sys.executable


@dataclass
class ProcessSpec:
    name: str
    command: List[str]


class ProcessController:
    """단일 서브프로세스를 관리."""

    def __init__(self, spec: ProcessSpec, env: Dict[str, str], cwd: Path):
        self.spec = spec
        self.env = env
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self._last_start = 0.0

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def ensure_running(self) -> bool:
        if self.running:
            return False
        now = time.time()
        if now - self._last_start < 2.0:  # 간단한 백오프
            return False
        await self.start()
        return True

    async def start(self) -> None:
        if self.running:
            return
        self._last_start = time.time()
        print(f"[switcher] starting {self.spec.name}: {' '.join(map(shlex.quote, self.spec.command))}")
        self.process = await asyncio.create_subprocess_exec(
            *self.spec.command,
            cwd=str(self.cwd),
            env=self.env,
        )

    async def stop(self, kill_after: float = 10.0) -> None:
        if not self.process:
            return
        if self.process.returncode is not None:
            self.process = None
            return
        print(f"[switcher] stopping {self.spec.name}")
        try:
            self.process.terminate()
        except ProcessLookupError:
            self.process = None
            return

        try:
            await asyncio.wait_for(self.process.wait(), timeout=kill_after)
        except asyncio.TimeoutError:
            print(f"[switcher] killing {self.spec.name} after timeout")
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
            else:
                await self.process.wait()
        finally:
            self.process = None

    async def poll_exit(self) -> Optional[int]:
        if not self.process:
            return None
        return self.process.returncode


class DisplaySwitcher:
    """상태에 따라 적절한 디스플레이 프로세스를 실행."""

    def __init__(self, sensor_controller: ProcessController, carecall_controller: ProcessController, idle_timeout: float, uart_controller: ProcessController | None = None):
        self.sensor = sensor_controller
        self.carecall = carecall_controller
        self.uart = uart_controller
        self.idle_timeout = idle_timeout
        self.state = "sensor"
        self._last_carecall_event: float = 0.0

    async def start(self) -> None:
        if self.uart:
            await self.uart.ensure_running()
        await self.sensor.ensure_running()
        self.state = "sensor"
        self._last_carecall_event = 0.0

    async def switch_to_carecall(self) -> None:
        if self.state == "carecall":
            await self.carecall.ensure_running()
            return
        print("[switcher] switching display: sensor -> carecall")
        await self.sensor.stop()
        await self.carecall.ensure_running()
        self.state = "carecall"
        self._last_carecall_event = time.time()

    async def switch_to_sensor(self) -> None:
        if self.state == "sensor":
            await self.sensor.ensure_running()
            return
        print("[switcher] switching display: carecall -> sensor")
        await self.carecall.stop()
        await self.sensor.ensure_running()
        self.state = "sensor"
        self._last_carecall_event = 0.0

    async def handle_carecall_event(self) -> None:
        self._last_carecall_event = time.time()
        await self.switch_to_carecall()

    async def tick(self) -> None:
        now = time.time()
        if self.uart:
            await self.uart.ensure_running()
        if self.state == "carecall":
            if self._last_carecall_event and (now - self._last_carecall_event) >= self.idle_timeout:
                await self.switch_to_sensor()
            else:
                await self.carecall.ensure_running()
        else:
            await self.sensor.ensure_running()
            await self.carecall.stop()

    async def shutdown(self) -> None:
        await self.carecall.stop()
        await self.sensor.stop()
        if self.uart:
            await self.uart.stop()


class KafkaEmotionWatcher:
    """carecall 감정 토픽을 감시해 이벤트 발생을 통지."""

    def __init__(self, bootstrap: str, topic: str, group_id: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[Tuple[str, object]]):
        self.bootstrap = bootstrap
        self.topic = topic
        self.group_id = group_id
        self.loop = loop
        self.queue = queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="KafkaEmotionWatcher", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            from kafka import KafkaConsumer  # type: ignore
        except Exception as exc:  # pragma: no cover
            self.loop.call_soon_threadsafe(
                self.queue.put_nowait,
                ("fatal", f"kafka-python import 실패: {exc}")
            )
            return

        try:
            consumer = KafkaConsumer(
                self.topic,
                bootstrap_servers=[s.strip() for s in self.bootstrap.split(",") if s.strip()],
                group_id=self.group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: m.decode("utf-8", "ignore") if isinstance(m, (bytes, bytearray)) else m,
            )
        except Exception as exc:
            self.loop.call_soon_threadsafe(
                self.queue.put_nowait,
                ("error", f"KafkaConsumer 생성 실패: {exc}")
            )
            return

        self.loop.call_soon_threadsafe(
            self.queue.put_nowait,
            ("info", f"Kafka 연결 성공: topic={self.topic}")
        )

        try:
            while not self._stop_event.is_set():
                try:
                    records = consumer.poll(timeout_ms=500)
                except Exception as exc:
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("error", f"Kafka poll 실패: {exc}")
                    )
                    time.sleep(1.0)
                    continue

                if not records:
                    continue

                for messages in records.values():
                    for message in messages:
                        payload = message.value
                        self.loop.call_soon_threadsafe(
                            self.queue.put_nowait,
                            ("event", payload)
                        )
        finally:
            try:
                consumer.close()
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("stopped", None))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)


def parse_extra_args(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return []
    result: List[str] = []
    for value in values:
        result.extend(shlex.split(value))
    return result


def build_parser() -> argparse.ArgumentParser:
    from networks.kafka.kafka_config import emotion_settings

    parser = argparse.ArgumentParser(
        description="센서/케어콜 디스플레이를 상황에 따라 전환",
    )
    parser.add_argument(
        "--bootstrap",
        default=",".join(emotion_settings.bootstrap_servers),
        help="Kafka bootstrap 서버 (쉼표 구분)",
    )
    parser.add_argument(
        "--topic",
        default=emotion_settings.topic,
        help="케어콜 감정 이벤트 토픽",
    )
    parser.add_argument(
        "--group-id",
        default="display-switcher",
        help="Kafka 컨슈머 그룹 ID",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=30.0,
        help="마지막 감정 이벤트 이후 센서 디스플레이로 복귀하는 시간(초)",
    )
    parser.add_argument(
        "--sensor-arg",
        action="append",
        default=[],
        help="sensor_display.py에 전달할 추가 인자 (공백 포함 시 따옴표 사용)",
    )
    parser.add_argument(
        "--carecall-arg",
        action="append",
        default=[],
        help="display_for_carecall 플레이어에 전달할 추가 인자",
    )
    parser.add_argument(
        "--carecall-videos",
        default=str((SRC_ROOT / "modules" / "display" / "display_for_carecall" / "video").resolve()),
        help="케어콜 전용 디스플레이에서 사용할 비디오 디렉터리",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="이벤트 대기 루프 타임아웃(초)",
    )
    parser.add_argument(
        "--log-events",
        action="store_true",
        help="수신한 케어콜 이벤트 페이로드를 로그로 출력",
    )
    parser.add_argument(
        "--enable-uart-producer",
        dest="uart_producer",
        action="store_true",
        help="UART → Kafka 생산자를 함께 실행",
    )
    parser.add_argument(
        "--no-uart-producer",
        dest="uart_producer",
        action="store_false",
        help="UART 생산자를 실행하지 않음",
    )
    parser.set_defaults(uart_producer=False)
    parser.add_argument(
        "--uart-dev",
        default="/dev/serial0",
        help="UART 디바이스 경로",
    )
    parser.add_argument(
        "--uart-baud",
        type=int,
        default=9600,
        help="UART Baudrate",
    )
    parser.add_argument(
        "--uart-topic",
        default=None,
        help="Kafka 토픽 (지정 시에만 적용)",
    )
    parser.add_argument(
        "--uart-arg",
        action="append",
        default=[],
        help="uart_producer.py에 전달할 추가 인자",
    )
    return parser



async def run(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH")
    src_path = str(SRC_ROOT)
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{python_path}" if python_path else src_path

    sensor_cmd = [PYTHON_EXECUTABLE, "-m", "modules.display.sensor_display", *parse_extra_args(args.sensor_arg)]
    carecall_cmd = [
        PYTHON_EXECUTABLE,
        "-m",
        "modules.display.display_for_carecall.mp4_player",
        "--kafka",
        args.bootstrap,
        "--topic",
        args.topic,
        "--videos",
        args.carecall_videos,
        *parse_extra_args(args.carecall_arg),
    ]


    uart_cmd = [
        PYTHON_EXECUTABLE,
        "-m",
        "networks.kafka.uart_producer",
        "--dev",
        args.uart_dev,
        "--baud",
        str(args.uart_baud),
        *parse_extra_args(args.uart_arg),
    ]
    if args.uart_topic:
        uart_cmd.extend(["--topic", args.uart_topic])

    sensor_controller = ProcessController(ProcessSpec("sensor-display", sensor_cmd), env, SRC_ROOT)
    carecall_controller = ProcessController(ProcessSpec("carecall-display", carecall_cmd), env, SRC_ROOT)
    uart_controller = None
    if args.uart_producer:
        uart_controller = ProcessController(ProcessSpec("uart-producer", uart_cmd), env, SRC_ROOT)
    switcher = DisplaySwitcher(sensor_controller, carecall_controller, idle_timeout=args.idle_timeout, uart_controller=uart_controller)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Tuple[str, object]] = asyncio.Queue()
    watcher = KafkaEmotionWatcher(args.bootstrap, args.topic, args.group_id, loop, queue)

    await switcher.start()
    watcher.start()

    stop_requested = asyncio.Event()

    def handle_signal(signum, frame):  # noqa: ANN001
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = str(signum)
        print(f"\n[switcher] signal received: {sig_name}. Shutting down...")
        stop_requested.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, RuntimeError):  # pragma: no cover
            pass

    kafka_active = True

    try:
        while not stop_requested.is_set():
            try:
                msg_type, payload = await asyncio.wait_for(queue.get(), timeout=args.poll_interval)
            except asyncio.TimeoutError:
                await switcher.tick()
                continue

            if msg_type == "event":
                data = payload
                if isinstance(payload, str):
                    try:
                        data = json.loads(payload)
                    except Exception:
                        data = {"raw": payload}
                if args.log_events:
                    print(f"[switcher] carecall event: {data}")

                if isinstance(data, dict) and data.get("end"):
                    await switcher.switch_to_sensor()
                else:
                    await switcher.handle_carecall_event()
            elif msg_type == "error":
                kafka_active = False
                print(f"[switcher] Kafka 오류: {payload}")
            elif msg_type == "fatal":
                kafka_active = False
                print(f"[switcher] Kafka 치명적인 오류: {payload}\n[switcher] 감정 이벤트 없이 센서 디스플레이만 유지합니다.")
            elif msg_type == "info":
                kafka_active = True
                print(f"[switcher] {payload}")
            elif msg_type == "stopped":
                kafka_active = False
                print("[switcher] Kafka watcher stopped.")

            queue.task_done()
            await switcher.tick()

        return 0
    finally:
        watcher.stop()
        await switcher.shutdown()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
