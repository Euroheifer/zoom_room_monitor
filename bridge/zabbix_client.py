"""Zabbix integration for the bridge.

Two parts:
  * ZabbixAPI  — JSON-RPC client used by provisioning (templates, hosts, groups).
  * send_values — native Zabbix "sender"/trapper protocol over TCP, so we push
    item values without needing the zabbix_sender binary installed.
"""
from __future__ import annotations

import json
import os
import socket
import struct
from typing import Any

import requests

ZBX_API_URL = os.environ.get("ZBX_API_URL", "http://localhost:8080/api_jsonrpc.php")
ZBX_USER = os.environ.get("ZBX_USER", "Admin")
ZBX_PASS = os.environ.get("ZBX_PASS", "zabbix")
ZBX_TRAPPER_HOST = os.environ.get("ZBX_TRAPPER_HOST", "localhost")
ZBX_TRAPPER_PORT = int(os.environ.get("ZBX_TRAPPER_PORT", "10051"))


class ZabbixAPIError(RuntimeError):
    pass


class ZabbixAPI:
    def __init__(self, url: str = ZBX_API_URL, user: str = ZBX_USER, password: str = ZBX_PASS):
        self.url = url
        self._user = user
        self._password = password
        self._token: str | None = None
        self._id = 0

    def login(self) -> None:
        self._token = self._raw_call("user.login",
                                     {"username": self._user, "password": self._password},
                                     auth=False)

    def _raw_call(self, method: str, params: Any, auth: bool = True) -> Any:
        self._id += 1
        headers = {"Content-Type": "application/json-rpc"}
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._id}
        resp = requests.post(self.url, headers=headers, data=json.dumps(payload), timeout=30)
        body = resp.json()
        if "error" in body:
            raise ZabbixAPIError(f"{method}: {body['error'].get('data', body['error'])}")
        return body["result"]

    def call(self, method: str, params: Any) -> Any:
        if not self._token:
            self.login()
        return self._raw_call(method, params, auth=True)


# --- trapper sender ------------------------------------------------------------

def send_values(items: list[dict], host: str = ZBX_TRAPPER_HOST, port: int = ZBX_TRAPPER_PORT,
                timeout: int = 15) -> dict:
    """Push a batch of {"host","key","value"} dicts to the Zabbix trapper.

    Returns the parsed server response (includes "info": "processed N; failed M").
    """
    payload = json.dumps({"request": "sender data", "data": items}).encode()
    packet = b"ZBXD" + b"\x01" + struct.pack("<Q", len(payload)) + payload

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(packet)
        # response: 5-byte magic+flags, 8-byte length, then JSON body
        header = _recv_exact(sock, 13)
        if header[:4] != b"ZBXD":
            raise RuntimeError(f"Bad trapper response header: {header!r}")
        resp_len = struct.unpack("<Q", header[5:13])[0]
        body = _recv_exact(sock, resp_len)
    return json.loads(body.decode())


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("Trapper connection closed early")
        buf += chunk
    return buf
