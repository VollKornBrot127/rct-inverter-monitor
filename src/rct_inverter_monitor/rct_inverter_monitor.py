#!/usr/bin/env python3
##################################################################################################################################
# Copyright (c) 2025                                                                                          All Rights Reserved
##################################################################################################################################
# CREATION DATE:  26.08.2025
# FILE:           rct_client.py
# DESCRIPTION:    Client application for communication with an RCT inverter.
##################################################################################################################################

##################################################################################################################################
# MARK: IMPORTS
##################################################################################################################################
# Standard library modules
import logging
import time
import socket
from pathlib import Path
from typing import Any
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
from rctclient.exceptions import FrameError
from pydantic import BaseModel

##################################################################################################################################
# MARK: GLOBAL VARIABLES
##################################################################################################################################
# fmt: off
LOGGER:                                 logging.Logger  = logging.getLogger(__name__)
DEFAULT_POLLING_INTERVAL_SECONDS:       float           = 10.0
RCT_INVERTER_IP_ADDRESS:                str             = "192.168.178.38"
RCT_INVERTER_PORT:                      int             = 8899
DEFAULT_CONNECTION_TIMEOUT_SECONDS:     float           = 3.0
# fmt: on


##################################################################################################################################
# MARK: CLASSES
##################################################################################################################################
class ParsedFrame(BaseModel):
    object_id: int
    payload: bytes


class RctInverterMonitor:
    def __init__(
        self,
        host_ip: str = RCT_INVERTER_IP_ADDRESS,
        port: int = RCT_INVERTER_PORT,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
        # PRIVATE MEMBER VARIABLES ###############################################################################################
        # fmt: off
        self._socket:               socket.socket | None            = None
        self._recv_frame:           ReceiveFrame                    = ReceiveFrame()
        self._reader_thread:        threading.Thread | None         = None
        self._stop_event:           threading.Event                 = threading.Event()
        self._pending:              dict[str, queue.Queue[bytes]]   = {}
        self._pending_lock:         threading.Lock                  = threading.Lock()
        self._write_lock:           threading.Lock                  = threading.Lock()
        self._poll_thread:          threading.Thread | None         = None
        self._poll_stop_event:      threading.Event                 = threading.Event()
        self._poll_list_lock:       threading.Lock                  = threading.Lock()
        self._poll_list:            Iterable[str]                   = []

        # PUBLIC MEMBER VARIABLES ################################################################################################
        self.host_ip:               str                             = host_ip
        self.port:                  int                             = port
        self.connection_timeout:    float                           = connection_timeout
        self.oid_mapping:           dict[str, str]                  = yaml.load(
                                                                        Path(__file__).parent.joinpath("oid_mapping.yml")
                                                                        .read_text(encoding="utf-8"),
                                                                        Loader=yaml.SafeLoader
                                                                    )
        self.reverse_oid_mapping:   dict[str, str]                  = {value: key for key, value in self.oid_mapping.items()}
        self.recv_chunk_size:       int                             = 256
        self.cache:                 dict[str, tuple[Any, float]]    = {}
        # fmt: on

    # PRIVATE MEMBER FUNCTIONS ###################################################################################################
    # Socket + Parser primitives
    def _get_socket(self) -> socket.socket:
        """Ensures the socket is initialized and returns it.

        Raises:
            TypeError: If the socket is not initialized.

        Returns:
            socket.socket: Socket instance.
        """
        if not (self._socket and isinstance(self._socket, socket.socket)):
            raise TypeError(f"Expected socket.socket, found: {type(self._socket)}")
        return self._socket

    def _reset_parser(self) -> None:
        self._recv_frame = ReceiveFrame()

    def _recv_chunk(self, sock: socket.socket) -> bytes | None:
        """Receive one chunk from the socket.

        Returns:
            bytes | None: Received bytes (can be empty if connection closed) or None if receive timed out and the loop should
                continue.
        """
        try:
            return sock.recv(self.recv_chunk_size)
        except socket.timeout:
            LOGGER.debug("Socket read timeout, continuing.")
            return None
        except OSError as exception:
            LOGGER.error("Socket error occurred, terminating reader loop.")
            LOGGER.error(str(exception))
            return b""

    def _guard_buffer_overflow(self, buffer: bytearray, max_size: int) -> bool:
        """Check if the buffer exceeds the maximum size and reset it if necessary.

        Args:
            buffer (bytearray): Current receive buffer.
            max_size (int): Maximum allowed buffer size.

        Returns:
            bool: True if the buffer was cleared due to overflow (and the caller should continue), False otherwise.
        """
        if len(buffer) <= max_size:
            return False

        LOGGER.warning("Input buffer exceeded %d bytes, clearing buffer and resetting parser.", max_size)
        buffer.clear()
        self._reset_parser()
        return True

    # Parsing + Routing
    def _consume_available_frames(self, buffer: bytearray) -> None:
        """Consumes as much as possible from buffer and routes complete frames.

        Args:
            buffer (bytearray): Current state of the buffer.
        """
        while buffer:
            parsed_frame, consumed = self._consume_step(buffer)
            del buffer[:consumed]

            if parsed_frame is None:
                continue

            self._route_parsed_frame(frame=parsed_frame)

    def _consume_step(self, buffer: bytearray) -> tuple[ParsedFrame | None, int]:
        """Consumes bytes into the parser and returns a complete frame if available.

        Args:
            buffer (bytearray): Current state of the buffer.

        Returns:
            tuple[ParsedFrame | None, int]: A full frame (if complete) and the number of consumed bytes (number of bytes to remove
                from the buffer).
        """
        try:
            consumed: int = self._recv_frame.consume(buffer)
        except FrameError as exception:
            return None, self._handle_frame_error(exception)
        except Exception as exception:
            return None, self._handle_unexpected_parser_error(exception)

        if consumed <= 0:
            self._reset_parser()
            return None, 1

        if not self._recv_frame.complete():
            return None, consumed

        parsed_frame: ParsedFrame | None = self._extract_complete_frame()
        return parsed_frame, consumed

    def _handle_frame_error(self, exception: FrameError) -> int:
        """Handles known rctclient frame parsing errors and returns bytes to discard.

        Args:
            exception (FrameError): The frame error exception.

        Returns:
            int: Number of bytes to discard from the buffer.

        """
        consumed: int = max(getattr(exception, "consumed_bytes", 0), 1)
        LOGGER.warning("Frame error while consuming incoming data frame.")
        LOGGER.error(str(exception))
        self._reset_parser()
        return consumed

    def _handle_unexpected_parser_error(self, exception: Exception) -> int:
        """Handles unexpected parser errors and returns bytes to discard.

        Args:
            exception (Exception): The unexpected exception.

        Returns:
            int: Number of bytes to discard from the buffer.
        """
        LOGGER.error("Unexcpected parser error, resetting parser.")
        LOGGER.error(str(exception))
        self._reset_parser()
        return 1

    def _extract_complete_frame(self) -> ParsedFrame | None:
        """Extracts a complete frame from the parser and resets the parser state.

        Returns:
            ParsedFrame | None: The extracted frame, or None if no frame is available.
        """
        object_id: int | None = self._recv_frame.id
        payload: bytes = bytes(self._recv_frame.data)
        self._reset_parser()

        if object_id is None:
            LOGGER.debug("Received frame with no object ID, discarding.")
            return None

        return ParsedFrame(object_id=object_id, payload=payload)

    def _route_parsed_frame(self, frame: ParsedFrame) -> None:
        """Routes a parsed frame to the appropriate pending request queue.

        Args:
            frame (ParsedFrame): The parsed frame to route.
        """
        key: str | None = self._object_id_to_pending_key(object_id=frame.object_id)

        if not key:
            LOGGER.debug("No pending request for object ID: %s, discarding response.", str(frame.object_id))
            return

        response_queue: queue.Queue[bytes] | None = self._get_pending_queue(key=key)
        if response_queue is None:
            LOGGER.debug("No pending request for OID: %s, discarding response.", key)
            return

        try:
            response_queue.put_nowait(frame.payload)
        except queue.Full:
            LOGGER.warning("Response queue full for OID: %s", key)

    def _object_id_to_pending_key(self, object_id: int) -> str | None:
        """Maps an object ID to a pending request key.

        Args:
            object_id (int): The object ID to map.

        Returns:
            str | None: The corresponding pending request key, or None if not found.
        """
        try:
            object_info: ObjectInfo = Registry.get_by_id(id=object_id)
            return self.reverse_oid_mapping.get(object_info.name)
        except Exception:
            LOGGER.debug("Received unknown object ID: %s", str(object_id))
            return None

    def _get_pending_queue(self, key: str) -> queue.Queue[bytes] | None:
        """Retrieves the pending response queue for a given key.

        Args:
            key (str): The key for which to retrieve the pending queue.

        Returns:
            queue.Queue[bytes] | None: The pending response queue, or None if not found.
        """
        with self._pending_lock:
            return self._pending.get(key)

    # Reader + Polling loops
    def _reader_loop(self) -> None:
        """Continuously read from socket, parse frames, and deliver payloads to per-OID queues."""
        sock: socket.socket = self._get_socket()
        buffer: bytearray = bytearray()
        MAX_BUFFER_SIZE: int = 64 * 1024  # 64 KB
        self._reset_parser()

        while not self._stop_event.is_set():
            chunk: bytes | None = self._recv_chunk(sock=sock)
            if chunk is None:
                continue
            if chunk == b"":
                LOGGER.info("Socket closed by remote host, terminating reader loop.")
                break

            buffer.extend(chunk)

            if self._guard_buffer_overflow(buffer=buffer, max_size=MAX_BUFFER_SIZE):
                continue

            self._consume_available_frames(buffer=buffer)

    def _poll_loop(self, interval: float, timeout: float, retries: int, stagger: bool) -> None:
        jitter: float = 0.02

        while not self._poll_stop_event.is_set():
            start: float = time.time()

            with self._poll_list_lock:
                keys = list(self._poll_list)

            for index, key in enumerate(keys):
                if self._poll_stop_event.is_set():
                    break

                try:
                    self.read_oid(key=key, timeout=timeout, retries=retries)
                except Exception as exception:
                    LOGGER.warning("Failed to poll OID: %s", key)
                    LOGGER.warning(str(exception))
                    pass

                if stagger and index < len(keys) - 1:
                    time.sleep(0.01 + jitter)

            elapsed_time: float = time.time() - start
            rest: float = interval - elapsed_time

            if rest > 0:
                end_by: float = time.time() + rest
                while not self._poll_stop_event.is_set() and time.time() < end_by:
                    time.sleep(min(0.05, end_by - time.time()))

    # PUBLIC MEMBER FUNCTIONS ####################################################################################################
    def connect(self, timeout: float = 5.0) -> None:
        self._socket = socket.create_connection((self.host_ip, self.port), timeout=timeout)
        self._socket.settimeout(0.5)
        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                LOGGER.warning("[WARNING] Socket already closed.")

            self._socket.close()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

    def read_oid(self, key: str, timeout: float = 0.5, retries: int = 1) -> Any:
        """Read the value of an OID and write it to the queue.

        Args:
            key (str): Key for the respective OID, e.g.: "BATTERY_SOC"
            timeout (float, optional): Timeout for the request in seconds. Defaults to 0.5.
            retries (int, optional): Number of retries if the request fails. Defaults to 1.
        """
        if key not in self.oid_mapping:
            raise KeyError(f"OID key not found: '{key}'")

        if not self._socket:
            raise TypeError(f"Expected socket.socket, found: {type(self._socket)}")

        object_info: ObjectInfo = Registry.get_by_name(self.oid_mapping[key])

        last_exception: Exception | None = None
        for attempt in range(retries + 1):
            response_queue = queue.Queue(maxsize=1)
            with self._pending_lock:
                self._pending[key] = response_queue

            # Send request
            try:
                with self._write_lock:
                    self._socket.sendall(make_frame(command=Command.READ, id=object_info.object_id))
            except Exception as exception:
                LOGGER.warning(f"Failed to send request for OID: {key} (attempt {attempt + 1}/{retries})")
                last_exception = exception
                with self._pending_lock:
                    self._pending.pop(key, None)
                continue

            try:
                data: bytes = response_queue.get(timeout=timeout)
                value: Any = decode_value(data_type=object_info.response_data_type, data=data)  # type: ignore
                self.cache[key] = (value, time.time())
                return value
            except queue.Empty as exception:
                LOGGER.warning("Timeout waiting for response for OID: %s (attempt %s", key, f"{attempt + 1}/{retries}")
                last_exception = exception
            finally:
                with self._pending_lock:
                    LOGGER.debug("Removing pending for key: %s", key)
                    self._pending.pop(key, None)

        raise TimeoutError(f"[ERROR] No response for OID: {key}") from last_exception

    def start_polling(
        self,
        keys: Iterable[str],
        interval: float = DEFAULT_POLLING_INTERVAL_SECONDS,
        timeout: float = 0.5,
        retries: int = 1,
        stagger: bool = True,
    ) -> None:
        self.set_poll_targets(keys=keys)

        self.stop_polling()

        self._poll_stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, args=(interval, timeout, retries, stagger), name="rct_poll", daemon=True
        )
        self._poll_thread.start()

    def stop_polling(self, timeout: float = 1.5) -> None:
        self._poll_stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=timeout)

        self._poll_thread = None
        self._poll_stop_event.clear()

    def set_poll_targets(self, keys: Iterable[str]) -> None:
        with self._poll_list_lock:
            self._poll_list = list(keys)

    def get_cache(self) -> dict[str, tuple[Any, float]]:
        return dict(self.cache)


##################################################################################################################################
# SCRIPT IMPLEMENTATION                                                                                                          #
##################################################################################################################################
if __name__ == "__main__":
    import datetime as dt

    logging.basicConfig(filename="out_3.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    rct_client: RctInverterMonitor = RctInverterMonitor()
    rct_client.connect()

    keys: list[str] = ["BATTERY_SOC", "BATTERY_POWER", "SOLAR_GENERATOR_A_POWER", "SOLAR_GENERATOR_B_POWER"]

    try:
        rct_client.start_polling(keys=keys)

        while True:
            cache: dict[str, tuple[Any, float]] = rct_client.get_cache()
            print(cache)
            if cache:
                print(f"Last update: {dt.datetime.fromtimestamp(cache['BATTERY_SOC'][1]).strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(DEFAULT_POLLING_INTERVAL_SECONDS)
    finally:
        rct_client.close()
