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
        print(f"[switcher] working directory: {self.cwd}")
        print(f"[switcher] environment: DISPLAY={self.env.get('DISPLAY', 'not set')}, XAUTHORITY={self.env.get('XAUTHORITY', 'not set')}")
        try:
            # 프로세스 시작 (stdout/stderr는 journald로 자동 전달됨)
            self.process = await asyncio.create_subprocess_exec(
                *self.spec.command,
                cwd=str(self.cwd),
                env=self.env,
            )
            # 프로세스가 시작되었는지 확인
            await asyncio.sleep(0.2)
            if self.process.returncode is not None:
                # 프로세스가 즉시 종료됨
                print(f"[switcher] ERROR: {self.spec.name} process exited immediately with code {self.process.returncode}")
                print(f"[switcher] Check journalctl for error details: sudo journalctl -u deeptree.service -n 100 | grep -i '{self.spec.name}'")
                print(f"[switcher] Command was: {' '.join(map(shlex.quote, self.spec.command))}")
                self.process = None
            else:
                print(f"[switcher] {self.spec.name} process started successfully (PID: {self.process.pid})")
                print(f"[switcher] Process status: running={self.running}, returncode={self.process.returncode}")
        except Exception as e:
            print(f"[switcher] ERROR: Failed to start {self.spec.name}: {e}")
            import traceback
            print(f"[switcher] Traceback: {traceback.format_exc()}")
            self.process = None

    async def stop(self, kill_after: float = 5.0) -> None:
        """프로세스 종료 - 케어콜 디스플레이가 완전히 사라지도록 개선"""
        if not self.process:
            return
        if self.process.returncode is not None:
            self.process = None
            return
        print(f"[switcher] stopping {self.spec.name}")
        
        # SIGTERM 전송
        try:
            self.process.terminate()
        except ProcessLookupError:
            self.process = None
            return

        # 프로세스 종료 대기
        try:
            await asyncio.wait_for(self.process.wait(), timeout=kill_after)
        except asyncio.TimeoutError:
            print(f"[switcher] killing {self.spec.name} after timeout")
            try:
                # 강제 종료
                self.process.kill()
                await self.process.wait()
            except ProcessLookupError:
                pass
        finally:
            # 프로세스가 완전히 종료되었는지 확인
            if self.process and self.process.returncode is None:
                try:
                    self.process.kill()
                    await asyncio.wait_for(self.process.wait(), timeout=1.0)
                except (ProcessLookupError, asyncio.TimeoutError):
                    pass
            self.process = None
            print(f"[switcher] {self.spec.name} stopped completely")

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
            try:
                await self.uart.ensure_running()
            except Exception as e:
                print(f"[switcher] UART producer start failed (non-fatal): {e}")
        try:
            await self.sensor.ensure_running()
        except Exception as e:
            print(f"[switcher] Sensor display start failed (non-fatal): {e}")
        self.state = "sensor"
        self._last_carecall_event = 0.0

    async def switch_to_carecall(self) -> None:
        print(f"[switcher] switch_to_carecall called (current state: {self.state})")
        if self.state == "carecall":
            print("[switcher] Already in carecall state, ensuring carecall display is running")
            try:
                started = await self.carecall.ensure_running()
                if started:
                    print("[switcher] Carecall display restarted")
                # 프로세스가 실제로 실행 중인지 확인
                if not self.carecall.running:
                    print("[switcher] WARNING: Carecall display process is not running, attempting to start...")
                    await self.carecall.start()
                    await asyncio.sleep(0.5)  # 프로세스 시작 대기
                    if not self.carecall.running:
                        print("[switcher] ERROR: Carecall display failed to start")
            except Exception as e:
                print(f"[switcher] Carecall display ensure failed (non-fatal): {e}")
                import traceback
                print(f"[switcher] Traceback: {traceback.format_exc()}")
            return
        print("[switcher] switching display: sensor -> carecall")
        # 센서 디스플레이를 먼저 완전히 종료 (Z-order 문제 방지)
        sensor_pid = self.sensor.process.pid if self.sensor.process else None
        print(f"[switcher] Stopping sensor display first (PID: {sensor_pid})...")
        await self.sensor.stop()
        
        # 추가 대기 시간으로 프로세스가 완전히 종료되도록 보장
        await asyncio.sleep(0.5)
        
        # 센서 프로세스가 여전히 실행 중이면 강제 종료
        if self.sensor.running:
            current_pid = self.sensor.process.pid if self.sensor.process else None
            print(f"[switcher] WARNING: Sensor display still running (PID: {current_pid}), force stopping...")
            await self.sensor.stop(kill_after=2.0)  # 더 짧은 타임아웃으로 강제 종료
            await asyncio.sleep(0.3)
            # 여전히 실행 중이면 최종 강제 종료
            if self.sensor.running:
                final_pid = self.sensor.process.pid if self.sensor.process else None
                print(f"[switcher] ERROR: Sensor display failed to stop (PID: {final_pid}), attempting final kill...")
                if self.sensor.process:
                    try:
                        self.sensor.process.kill()
                        await asyncio.wait_for(self.sensor.process.wait(), timeout=1.0)
                        print(f"[switcher] Sensor display forcefully killed (PID: {final_pid})")
                    except (ProcessLookupError, asyncio.TimeoutError) as e:
                        print(f"[switcher] Error during final kill: {e}")
                    finally:
                        self.sensor.process = None
        
        # 최종 확인
        if self.sensor.running:
            print("[switcher] ERROR: Sensor display is STILL running after all stop attempts!")
        else:
            print(f"[switcher] Sensor display stopped successfully (was PID: {sensor_pid})")
        
        # 센서 디스플레이가 완전히 종료된 후 리소스 해제를 위해 추가 대기
        print("[switcher] Waiting for resources to be released...")
        await asyncio.sleep(1.0)  # 리소스 해제 대기
        
        # 센서 디스플레이가 완전히 종료된 후 케어콜 디스플레이 시작
        print("[switcher] Starting carecall display after sensor display stopped...")
        carecall_started = False
        try:
            await self.carecall.start()
            
            # 프로세스가 시작되었는지 즉시 확인
            if not self.carecall.process:
                print("[switcher] ERROR: Carecall display process is None after start()")
                raise Exception("Carecall display process is None")
            
            initial_pid = self.carecall.process.pid if self.carecall.process else None
            print(f"[switcher] Carecall display process created (PID: {initial_pid})")
            
            # 프로세스가 즉시 종료되었는지 확인
            await asyncio.sleep(0.3)
            if self.carecall.process and self.carecall.process.returncode is not None:
                exit_code = self.carecall.process.returncode
                print(f"[switcher] ERROR: Carecall display process exited immediately with code {exit_code}")
                print(f"[switcher] Check journalctl for error details: sudo journalctl -u deeptree.service -n 100 | grep -i 'carecall-display'")
                raise Exception(f"Carecall display process exited immediately with code {exit_code}")
            
            # 프로세스가 실제로 시작되었는지 확인 (더 긴 대기 시간)
            await asyncio.sleep(1.0)  # 프로세스 시작 및 윈도우 생성 대기
            
            # 프로세스가 실행 중인지 여러 번 확인
            for check_attempt in range(5):  # 5번 확인으로 증가
                if self.carecall.process is None:
                    print(f"[switcher] ERROR: Carecall display process is None (check {check_attempt + 1}/5)")
                    break
                
                if self.carecall.process.returncode is not None:
                    exit_code = self.carecall.process.returncode
                    print(f"[switcher] ERROR: Carecall display process exited with code {exit_code} (check {check_attempt + 1}/5)")
                    break
                
                if self.carecall.running:
                    carecall_pid = self.carecall.process.pid if self.carecall.process else None
                    print(f"[switcher] Carecall display started successfully (PID: {carecall_pid}, check {check_attempt + 1}/5)")
                    carecall_started = True
                    break
                else:
                    print(f"[switcher] WARNING: Carecall display process not running yet (check {check_attempt + 1}/5), waiting...")
                    await asyncio.sleep(0.5)
            
            if not carecall_started:
                if self.carecall.process:
                    exit_code = self.carecall.process.returncode
                    print(f"[switcher] ERROR: Carecall display process failed to start (returncode: {exit_code})")
                    print(f"[switcher] Check journalctl for error details: sudo journalctl -u deeptree.service -n 100 | grep -i 'carecall-display'")
                else:
                    print("[switcher] ERROR: Carecall display process is None")
                raise Exception("Carecall display process not running after start")
        except Exception as e:
            print(f"[switcher] Carecall display start failed: {e}")
            import traceback
            print(f"[switcher] Traceback: {traceback.format_exc()}")
            # 케어콜 디스플레이 시작 실패 시 센서 디스플레이를 다시 시작 (fallback)
            if not carecall_started:
                print("[switcher] Fallback: Restarting sensor display due to carecall display start failure")
                try:
                    await self.sensor.ensure_running()
                    self.state = "sensor"
                    self._last_carecall_event = 0.0
                    print("[switcher] Sensor display restarted as fallback")
                    return
                except Exception as fallback_error:
                    print(f"[switcher] ERROR: Failed to restart sensor display as fallback: {fallback_error}")
        
        # 케어콜 디스플레이가 성공적으로 시작된 경우에만 상태 변경
        if carecall_started:
            self.state = "carecall"
            self._last_carecall_event = time.time()
            print(f"[switcher] State changed to carecall, last_carecall_event updated to {self._last_carecall_event}")
        else:
            # 여전히 시작되지 않았으면 센서로 유지
            print("[switcher] WARNING: Carecall display not started, keeping sensor state")
            try:
                await self.sensor.ensure_running()
                self.state = "sensor"
                self._last_carecall_event = 0.0
            except Exception:
                pass

    async def switch_to_sensor(self) -> None:
        """센서 디스플레이로 전환 - 케어콜 디스플레이 완전 종료 보장"""
        if self.state == "sensor":
            try:
                await self.sensor.ensure_running()
            except Exception as e:
                print(f"[switcher] Sensor display ensure failed (non-fatal): {e}")
            return
        print("[switcher] switching display: carecall -> sensor")
        
        # 케어콜 디스플레이 완전 종료
        carecall_pid = self.carecall.process.pid if self.carecall.process else None
        print(f"[switcher] Stopping carecall display (PID: {carecall_pid})...")
        await self.carecall.stop()
        
        # 추가 대기 시간으로 프로세스가 완전히 종료되도록 보장
        await asyncio.sleep(0.5)
        
        # 케어콜 프로세스가 여전히 실행 중이면 강제 종료
        if self.carecall.running:
            current_pid = self.carecall.process.pid if self.carecall.process else None
            print(f"[switcher] WARNING: Carecall display still running (PID: {current_pid}), force stopping...")
            await self.carecall.stop(kill_after=2.0)  # 더 짧은 타임아웃으로 강제 종료
            await asyncio.sleep(0.3)
            # 여전히 실행 중이면 최종 강제 종료
            if self.carecall.running:
                final_pid = self.carecall.process.pid if self.carecall.process else None
                print(f"[switcher] ERROR: Carecall display failed to stop (PID: {final_pid}), attempting final kill...")
                if self.carecall.process:
                    try:
                        self.carecall.process.kill()
                        await asyncio.wait_for(self.carecall.process.wait(), timeout=1.0)
                        print(f"[switcher] Carecall display forcefully killed (PID: {final_pid})")
                    except (ProcessLookupError, asyncio.TimeoutError) as e:
                        print(f"[switcher] Error during final kill: {e}")
                    finally:
                        self.carecall.process = None
        
        # 최종 확인
        if self.carecall.running:
            print("[switcher] ERROR: Carecall display is STILL running after all stop attempts!")
        else:
            print(f"[switcher] Carecall display stopped successfully (was PID: {carecall_pid})")
        
        # 센서 디스플레이 시작 (케어콜이 완전히 종료된 후)
        print("[switcher] Starting sensor display...")
        try:
            await self.sensor.ensure_running()
            # 프로세스가 실제로 시작되었는지 확인
            await asyncio.sleep(0.5)
            if not self.sensor.running:
                print("[switcher] WARNING: Sensor display process is not running, attempting to start...")
                await self.sensor.start()
                await asyncio.sleep(0.5)
                if not self.sensor.running:
                    print("[switcher] ERROR: Sensor display failed to start")
                else:
                    sensor_pid = self.sensor.process.pid if self.sensor.process else None
                    print(f"[switcher] Sensor display started successfully (PID: {sensor_pid})")
            else:
                sensor_pid = self.sensor.process.pid if self.sensor.process else None
                print(f"[switcher] Sensor display running (PID: {sensor_pid})")
        except Exception as e:
            print(f"[switcher] Sensor display start failed: {e}")
            import traceback
            print(f"[switcher] Traceback: {traceback.format_exc()}")
        
        self.state = "sensor"
        self._last_carecall_event = 0.0
        print(f"[switcher] State changed to sensor, last_carecall_event reset to 0.0")

    async def handle_carecall_event(self) -> None:
        print(f"[switcher] handle_carecall_event called (current state: {self.state})")
        self._last_carecall_event = time.time()
        await self.switch_to_carecall()

    async def tick(self) -> None:
        now = time.time()
        if self.uart:
            try:
                await self.uart.ensure_running()
            except Exception as e:
                print(f"[switcher] UART producer check failed (non-fatal): {e}")
        if self.state == "carecall":
            if self._last_carecall_event and (now - self._last_carecall_event) >= self.idle_timeout:
                await self.switch_to_sensor()
            else:
                try:
                    await self.carecall.ensure_running()
                except Exception as e:
                    print(f"[switcher] Carecall display check failed (non-fatal): {e}")
        else:
            try:
                await self.sensor.ensure_running()
            except Exception as e:
                print(f"[switcher] Sensor display check failed (non-fatal): {e}")
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

        # Kafka 연결 재시도 로직 (최대 60초, 1초 간격)
        consumer = None
        max_retries = 60
        for retry in range(max_retries):
            try:
                consumer = KafkaConsumer(
                    self.topic,
                    bootstrap_servers=[s.strip() for s in self.bootstrap.split(",") if s.strip()],
                    group_id=self.group_id,
                    # latest로 설정하여 기본적으로 최신 메시지만 읽음
                    # 시작 시에만 오래된 메시지를 읽어서 상태를 복원
                    auto_offset_reset="latest",
                    enable_auto_commit=True,
                    value_deserializer=lambda m: m.decode("utf-8", "ignore") if isinstance(m, (bytes, bytearray)) else m,
                    consumer_timeout_ms=500,
                    max_poll_records=10,
                )
                
                # Consumer가 제대로 구독했는지 확인 (poll을 통해 partition 할당 유도)
                # poll()을 호출해야 partition이 할당됩니다
                partitions = None
                for poll_attempt in range(10):  # 최대 10번 poll 시도 (약 5초)
                    try:
                        # poll()을 호출하여 partition 할당 유도
                        consumer.poll(timeout_ms=100)
                        partitions = consumer.assignment()
                        if partitions:
                            break
                    except Exception as poll_exc:
                        # poll 중 오류가 발생하면 consumer를 닫고 재시도
                        try:
                            consumer.close()
                        except Exception:
                            pass
                        raise Exception(f"Consumer poll failed: {poll_exc}")
                    time.sleep(0.5)
                
                if not partitions:
                    # partition이 할당되지 않았지만 consumer는 생성되었으므로 계속 진행
                    # (topic에 메시지가 없거나 partition이 아직 생성되지 않았을 수 있음)
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("warning", f"Kafka consumer created but no partitions assigned yet (topic may be empty or not exist). Topic: {self.topic}, Group: {self.group_id}")
                    )
                    # partition 할당을 기다리기 위해 추가 poll 시도
                    for additional_poll in range(20):  # 최대 10초 더 대기
                        try:
                            consumer.poll(timeout_ms=500)
                            partitions = consumer.assignment()
                            if partitions:
                                self.loop.call_soon_threadsafe(
                                    self.queue.put_nowait,
                                    ("info", f"Partitions assigned after additional wait: {partitions}")
                                )
                                break
                        except Exception:
                            pass
                        time.sleep(0.5)
                else:
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("info", f"Kafka consumer assigned partitions: {partitions}")
                    )
                
                # partition 할당 여부와 관계없이 consumer는 계속 실행
                if partitions:
                    # auto_offset_reset="latest"로 설정했으므로 이미 최신 메시지부터 읽음
                    # 추가 seek 작업 불필요
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("info", f"Kafka consumer ready, listening for new messages from latest offset (partitions: {len(partitions)})")
                    )
                else:
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("warning", f"Kafka consumer ready but no partitions assigned. Will continue polling in case partitions are assigned later.")
                    )
                
                # Consumer가 준비되었음을 알리는 로그
                self.loop.call_soon_threadsafe(
                    self.queue.put_nowait,
                    ("info", f"Kafka consumer ready and listening for messages (group_id={self.group_id})")
                )
                break
            except Exception as exc:
                # consumer가 생성되었지만 오류가 발생한 경우 닫기
                if consumer is not None:
                    try:
                        consumer.close()
                    except Exception:
                        pass
                    consumer = None
                
                if retry < max_retries - 1:
                    error_msg = str(exc)
                    # 실제 오류 메시지도 함께 출력 (디버깅용)
                    error_type = type(exc).__name__
                    # "Invalid file object: None" 오류는 Kafka broker가 아직 준비되지 않았을 때 발생
                    if "Invalid file object" in error_msg or "None" in error_msg:
                        self.loop.call_soon_threadsafe(
                            self.queue.put_nowait,
                            ("info", f"Kafka 연결 시도 {retry + 1}/{max_retries} 실패 ({error_type}): Kafka broker may not be ready yet, retrying...")
                        )
                    else:
                        self.loop.call_soon_threadsafe(
                            self.queue.put_nowait,
                            ("info", f"Kafka 연결 시도 {retry + 1}/{max_retries} 실패 ({error_type}): {error_msg}, 재시도 중...")
                        )
                    time.sleep(1.0)
                else:
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("error", f"KafkaConsumer 생성 실패 (재시도 {max_retries}회): {exc}")
                    )
                    return

        if consumer is None:
            self.loop.call_soon_threadsafe(
                self.queue.put_nowait,
                ("error", "KafkaConsumer 생성 실패: consumer is None")
            )
            return

        self.loop.call_soon_threadsafe(
            self.queue.put_nowait,
            ("info", f"Kafka 연결 성공: topic={self.topic}, group_id={self.group_id}")
        )

        poll_count = 0
        last_status_log = time.time()
        
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

                poll_count += 1
                
                # 30초마다 상태 로그 출력 (partition 할당 상태 및 최신 offset 포함)
                now = time.time()
                if now - last_status_log >= 30.0:
                    last_status_log = now
                    assigned_partitions = consumer.assignment()
                    position_info = []
                    if assigned_partitions:
                        for partition in assigned_partitions:
                            try:
                                position = consumer.position(partition)
                                # 최신 offset 확인
                                end_offsets = consumer.end_offsets([partition])
                                latest_offset = end_offsets.get(partition, -1)
                                lag = latest_offset - position if latest_offset >= 0 and position >= 0 else -1
                                position_info.append(f"p{partition.partition}:offset={position},latest={latest_offset},lag={lag}")
                            except Exception as e:
                                position_info.append(f"p{partition.partition}:error={str(e)[:50]}")
                    partitions_str = ", ".join(position_info) if position_info else "none"
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait,
                        ("info", f"Kafka watcher active (polled {poll_count} times, partitions: [{partitions_str}], no messages yet)")
                    )

                if not records:
                    continue

                # 메시지 수신 로그 (항상 출력)
                total_messages = sum(len(msgs) for msgs in records.values())
                self.loop.call_soon_threadsafe(
                    self.queue.put_nowait,
                    ("info", f"[Kafka] Received {total_messages} message(s) from topic {self.topic} (after {poll_count} polls)")
                )

                for topic_partition, messages in records.items():
                    for message in messages:
                        payload = message.value
                        # 디버깅: 메시지 상세 정보 로그 (항상 출력)
                        self.loop.call_soon_threadsafe(
                            self.queue.put_nowait,
                            ("info", f"[Kafka] Message from partition {topic_partition.partition}, offset {message.offset}: {payload}")
                        )
                        # 이벤트를 큐에 추가
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
        default=None,  # None이면 자동 생성 (timestamp 기반)
        help="Kafka 컨슈머 그룹 ID (지정하지 않으면 자동 생성)",
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
    
    # group_id가 None이면 자동 생성 (timestamp 기반으로 unique하게)
    group_id = args.group_id
    if group_id is None:
        # 고정된 consumer group_id 사용 (offset 관리 안정화)
        group_id = "display-switcher"
        print(f"[switcher] Using fixed consumer group_id: {group_id}")
    
    watcher = KafkaEmotionWatcher(args.bootstrap, args.topic, group_id, loop, queue)

    print("[switcher] Starting display switcher...")
    await switcher.start()
    print("[switcher] Display switcher started, initial state: sensor")
    
    print(f"[switcher] Starting Kafka emotion watcher (topic: {args.topic}, bootstrap: {args.bootstrap})...")
    watcher.start()
    print("[switcher] Kafka emotion watcher started")

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
                
                # 항상 이벤트 로그 출력 (디버깅용)
                print(f"[switcher] ===== carecall event received: {data} =====")

                if isinstance(data, dict):
                    # end=True면 센서로 전환 (가장 우선순위)
                    if data.get("end"):
                        print("[switcher] End event detected, switching to sensor")
                        await switcher.switch_to_sensor()
                    # start=True이면 케어콜로 전환 (restored가 아닌 실제 대화 시작만)
                    elif data.get("start") and not data.get("restored"):
                        print(f"[switcher] Start event detected (start={data.get('start')}, restored={data.get('restored')}), switching to carecall")
                        await switcher.handle_carecall_event()
                    # emotion이 있고 restored가 아니면 케어콜로 전환
                    elif data.get("emotion") and not data.get("restored"):
                        print(f"[switcher] Emotion event detected (emotion={data.get('emotion')}, restored={data.get('restored')}), switching to carecall")
                        await switcher.handle_carecall_event()
                    # restored=True 이벤트는 실제 대화 시작이 아니므로 디스플레이 전환하지 않고 상태만 업데이트
                    elif data.get("restored"):
                        print("[switcher] Restored event detected (from old messages), updating state only (no display switch)")
                        # restored 이벤트는 _last_carecall_event만 업데이트하여 idle_timeout 방지
                        switcher._last_carecall_event = time.time()
                        print(f"[switcher] Updated last_carecall_event to {switcher._last_carecall_event} (no display switch)")
                    else:
                        # 기본적으로 케어콜 이벤트로 처리 (emotion이나 start가 없어도)
                        print(f"[switcher] Unknown event type (keys: {list(data.keys())}), treating as carecall event")
                        await switcher.handle_carecall_event()
                else:
                    # dict가 아니면 기본적으로 케어콜 이벤트로 처리
                    print("[switcher] Non-dict event, treating as carecall event")
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
