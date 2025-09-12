#!/usr/bin/env python3
##################################################################################################################################
# Copyright (c) 2025                                                                                          All Rights Reserved
##################################################################################################################################
# CREATION DATE:  26.08.2025
# FILE:           rct_client.py
# DESCRIPTION:    Client application for communication with an RCT inverter.
##################################################################################################################################

##################################################################################################################################
# IMPORT MODULES / LIBRARIES                                                                                                     #
##################################################################################################################################
# Standard library modules
import os
import sys
import time
import socket
from pathlib import Path
from typing import Any, Optional
from collections.abc import Iterable
import threading
import queue


# Third-party modules
import yaml
from rctclient.frame import ReceiveFrame, make_frame
from rctclient.registry import REGISTRY as Registry
from rctclient.registry import ObjectInfo
from rctclient.types import Command
from rctclient.utils import decode_value
from rich import print

# Local application modules

##################################################################################################################################
# GLOBAL VARIABLES                                                                                                               #
##################################################################################################################################


##################################################################################################################################
# CLASS IMPLEMENTATION                                                                                                           #
##################################################################################################################################
class RctClient:
    def __init__(self, s_host_ip: str = "192.168.178.51", i_port: int = 8899, f_timeout: float = 3.0) -> None:
        # PRIVATE MEMBER VARIABLES ###############################################################################################
        self._o_socket: Optional[socket.socket] = None
        self._o_recv_frame: ReceiveFrame = ReceiveFrame()
        self._o_reader_thread: Optional[threading.Thread] = None
        self._o_stop_event: threading.Event = threading.Event()
        self._d_pending: dict[str, queue.Queue[bytes]] = {}
        self._o_pending_lock: threading.Lock = threading.Lock()
        self._o_write_lock: threading.Lock = threading.Lock()
        self._o_poll_thread: Optional[threading.Thread] = None
        self._o_poll_stop_event: threading.Event = threading.Event()
        self._o_poll_list_lock: threading.Lock = threading.Lock()
        self._poll_list: Iterable[str] = []

        # PUBLIC MEMBER VARIABLES ################################################################################################
        self.s_host_ip: str = s_host_ip
        self.i_port: int = i_port
        self.f_timeout: float = f_timeout
        self.d_oid_mapping: dict[str, str] = read_yaml(o_file_path="App/oid_mapping.yml")
        self.d_reverse_oid_mapping: dict[str, str] = {s_value: s_key for s_key, s_value in self.d_oid_mapping.items()}
        self.i_recv_chunk_size: int = 256
        self.d_cache: dict[str, tuple[Any, float]] = {}

        # INITIALIZATION #########################################################################################################

    # PUBLIC MEMBER FUNCTIONS ####################################################################################################
    def connect(self, f_timeout: float = 5.0) -> None:
        self._o_socket = socket.create_connection((self.s_host_ip, self.i_port), timeout=f_timeout)
        self._o_socket.settimeout(0.5)
        self._o_stop_event.clear()
        self._o_reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._o_reader_thread.start()

    def close(self) -> None:
        self._o_stop_event.set()
        if self._o_socket:
            try:
                self._o_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            self._o_socket.close()
        if self._o_reader_thread and self._o_reader_thread.is_alive():
            self._o_reader_thread.join(timeout=1.0)

    def read_oid(self, s_key: str, f_timeout: float = 0.5, i_retries: int = 1) -> Any:
        """Read the value of an OID and write it to the queue.

        Args:
            s_key (str): Key for the respective OID, e.g.: "BATTERY_SOC"
            f_timeout (float, optional): Timeout for the request in seconds. Defaults to 0.5.
            i_retries (int, optional): Number of retries if the request fails. Defaults to 1.
        """
        if s_key not in self.d_oid_mapping:
            raise KeyError(f"[ERROR] OID key not found: '{s_key}'")

        if not self._o_socket:
            raise TypeError(f"[ERROR] Expected socket.socket, found: {type(self._o_socket)}")

        o_object_info: ObjectInfo = Registry.get_by_name(self.d_oid_mapping[s_key])

        o_last_exception: Optional[Exception] = None
        for i_attempt in range(i_retries + 1):
            o_queue = queue.Queue(maxsize=1)
            with self._o_pending_lock:
                self._d_pending[s_key] = o_queue

            # Send request
            try:
                with self._o_write_lock:
                    self._o_socket.sendall(make_frame(command=Command.READ, id=o_object_info.object_id))
            except Exception as o_exception:
                o_last_exception = o_exception
                with self._o_pending_lock:
                    self._d_pending.pop(s_key, None)
                continue

            try:
                o_data: bytes = o_queue.get(timeout=f_timeout)
                o_value: Any = decode_value(data_type=o_object_info.response_data_type, data=o_data)
                self.d_cache[s_key] = (o_value, time.time())
                return o_value
            except queue.Empty as o_exception:
                o_last_exception = o_exception
            finally:
                with self._o_pending_lock:
                    self._d_pending.pop(s_key, None)

        raise TimeoutError(f"[ERROR] No response for OID: {s_key}") from o_last_exception

    def _reader_loop(self) -> None:
        if not self._o_socket:
            raise TypeError(f"[ERROR] Expected socket.socket, found: {type(self._o_socket)}")

        o_buffer: bytearray = bytearray()
        while not self._o_stop_event.is_set():
            try:
                o_chunk = self._o_socket.recv(self.i_recv_chunk_size)
                if not o_chunk:
                    break

                o_buffer.extend(o_chunk)

                while o_buffer:
                    i_consumed: int = 0
                    try:
                        i_consumed = self._o_recv_frame.consume(o_buffer)
                    except Exception:
                        i_consumed = 1
                    del o_buffer[:i_consumed]

                    if self._o_recv_frame.complete():
                        i_object_id: int = self._o_recv_frame.id
                        s_key: Optional[str] = None

                        if i_object_id is not None:
                            try:
                                o_object_info: ObjectInfo = Registry.get_by_id(id=i_object_id)
                                s_key = self.d_reverse_oid_mapping[o_object_info.name]
                            except Exception:
                                s_key = None

                            b_delivered: bool = False
                            if s_key:
                                o_payload: bytes = bytes(self._o_recv_frame.data)
                                with self._o_pending_lock:
                                    o_queue: Optional[queue.Queue[bytes]] = self._d_pending.get(s_key)
                                if o_queue:
                                    try:
                                        o_queue.put_nowait(o_payload)
                                        b_delivered = True
                                    except queue.Full:
                                        pass

                            if not b_delivered:
                                pass

                        self._o_recv_frame = ReceiveFrame()

            except socket.timeout:
                continue
            except OSError:
                break

    def start_polling(
        self, l_keys: Iterable[str], f_interval: float = 2.0, f_timeout: float = 0.5, i_retries: int = 1, b_stagger: bool = True
    ) -> None:
        self.set_poll_targets(l_keys=l_keys)

        self.stop_polling()

        self._o_poll_stop_event.clear()
        self._o_poll_thread = threading.Thread(
            target=self._poll_loop, args=(f_interval, f_timeout, i_retries, b_stagger), name="rct_poll", daemon=True
        )
        self._o_poll_thread.start()

    def stop_polling(self, f_timeout: float = 1.5) -> None:
        self._o_poll_stop_event.set()
        if self._o_poll_thread and self._o_poll_thread.is_alive():
            self._o_poll_thread.join(timeout=f_timeout)

        self._o_poll_thread = None
        self._o_poll_stop_event.clear()

    def set_poll_targets(self, l_keys: Iterable[str]) -> None:
        with self._o_poll_list_lock:
            self._poll_list = list(l_keys)

    def get_cache(self) -> dict[str, tuple[Any, float]]:
        return dict(self.d_cache)

    def _poll_loop(self, f_interval: float, f_timeout: float, i_retries: int, b_stagger: bool) -> None:
        f_jitter: float = 0.02

        while not self._o_poll_stop_event.is_set():
            f_start: float = time.time()

            with self._o_poll_list_lock:
                l_keys = list(self._poll_list)

            for i_index, s_key in enumerate(l_keys):
                if self._o_poll_stop_event.is_set():
                    break

                try:
                    self.read_oid(s_key=s_key, f_timeout=f_timeout, i_retries=i_retries)
                except Exception:
                    pass

                if b_stagger and i_index < len(l_keys) - 1:
                    time.sleep(0.01 + f_jitter)

            f_elapsed_time: float = time.time() - f_start
            f_rest: float = f_interval - f_elapsed_time

            if f_rest > 0:
                f_end_by: float = time.time() + f_rest
                while not self._o_poll_stop_event.is_set() and time.time() < f_end_by:
                    time.sleep(min(0.05, f_end_by - time.time()))


##################################################################################################################################
# FUNCTION IMPLEMENTATION                                                                                                        #
##################################################################################################################################
def read_yaml(o_file_path: str | Path) -> dict[str, Any]:
    o_path: Path = Path(o_file_path)

    if not o_path.is_file():
        print(f"[WARNING] File not found: {str(o_path)}")
        return {}

    if o_path.suffix.lower() not in [".yaml", ".yml"]:
        print(f"[WARNING] The specified path is not a valid YAML file: {str(o_path)}")
        return {}

    with open(str(o_path), "r") as o_file:
        try:
            return yaml.safe_load(o_file)
        except Exception as obj_exception:
            print(f"[ERROR] Could not read YAML file: {str(o_path)}\n[ERROR] {obj_exception}")
            return {}

    return {}


##################################################################################################################################
# SCRIPT IMPLEMENTATION                                                                                                          #
##################################################################################################################################
if __name__ == "__main__":
    o_rct_client: RctClient = RctClient()
    o_rct_client.connect()

    l_keys: list[str] = ["BATTERY_SOC", "BATTERY_POWER", "SOLAR_GENERATOR_A_POWER", "SOLAR_GENERATOR_B_POWER"]

    try:
        o_rct_client.start_polling(l_keys=l_keys)

        while True:
            d_cache: dict[str, tuple[Any, float]] = o_rct_client.get_cache()
            f_battery_soc: Optional[tuple[Any, float]] = d_cache.get("BATTERY_SOC", None)
            f_battery_power: Optional[tuple[Any, float]] = d_cache.get("BATTERY_POWER", None)
            if f_battery_soc:
                print(f"Battery SoC: {f_battery_soc[0] * 100:.2f} %")
            if f_battery_power:
                print(f"Battery Power: {f_battery_power[0] / 1000:.2f} kW")

            time.sleep(2.0)
    finally:
        o_rct_client.close()
