from __future__ import annotations

import json
import os
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path

import paramiko
from paramiko import common


@dataclass
class PortState:
    interface: str
    description: str = ""
    mode: str = "access"
    vlan: int | None = None
    speed: str = ""
    duplex: str = ""
    status: str = "up"
    protocol: str = "up"
    mac_address: str = ""
    cdp_neighbor: str = ""
    has_port_security: bool = False


@dataclass
class SwitchState:
    hostname: str
    ports: dict[str, PortState] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "SwitchState":
        data = json.loads(path.read_text(encoding="utf-8"))
        hostname = data.get("hostname", "mock-switch")
        ports: dict[str, PortState] = {}
        for item in data.get("ports", []):
            port = PortState(
                interface=item.get("interface", ""),
                description=item.get("description", ""),
                mode=item.get("mode", "access"),
                vlan=item.get("vlan"),
                speed=item.get("speed", ""),
                duplex=item.get("duplex", ""),
                status=item.get("status", "up"),
                protocol=item.get("protocol", "up"),
                mac_address=item.get("mac_address", ""),
                cdp_neighbor=item.get("cdp_neighbor", ""),
                has_port_security=item.get("has_port_security", False),
            )
            if port.interface:
                ports[port.interface] = port
        return cls(hostname=hostname, ports=ports)


class MockServer(paramiko.ServerInterface):
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.event = threading.Event()
        self.exec_command: str | None = None

    def check_auth_password(self, username: str, password: str) -> int:
        if username == self.username and password == self.password:
            return common.AUTH_SUCCESSFUL
        return common.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return common.OPEN_SUCCEEDED
        return common.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel) -> bool:
        self.event.set()
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        return True

    def check_channel_exec_request(self, channel, command):
        try:
            self.exec_command = command.decode("utf-8", errors="ignore")
        except AttributeError:
            self.exec_command = str(command)
        self.event.set()
        return True


class MockSwitch:
    def __init__(
        self,
        host: str,
        port: int,
        state: SwitchState,
        username: str = "admin",
        password: str = "admin",
    ) -> None:
        self.host = host
        self.port = port
        self.state = state
        self.username = username
        self.password = password
        self._running = False

    def start(self) -> None:
        self._running = True
        thread = threading.Thread(target=self._serve, daemon=True)
        thread.start()

    def _serve(self) -> None:
        host_key = self._load_host_key()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(100)
            while self._running:
                client, _addr = server.accept()
                transport = paramiko.Transport(client)
                transport.add_server_key(host_key)
                server_interface = MockServer(self.username, self.password)
                transport.start_server(server=server_interface)
                channel = transport.accept(20)
                if channel is None:
                    continue
                server_interface.event.wait(10)
                if server_interface.exec_command:
                    output = self._handle_exec_command(server_interface.exec_command.strip())
                    if output:
                        channel.send(output.encode("utf-8"))
                    channel.send_exit_status(0)
                    transport.close()
                    continue
                self._handle_channel(channel)

    def _load_host_key(self) -> paramiko.PKey:
        key_path = Path(__file__).resolve().parent / "host_key"
        if key_path.exists() and key_path.stat().st_size > 0:
            return paramiko.RSAKey.from_private_key_file(str(key_path))
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(str(key_path))
        return key

    def _handle_channel(self, channel: paramiko.Channel) -> None:
        prompt = f"{self.state.hostname}> "
        config_mode = False
        interface_mode: str | None = None
        buffer = ""
        channel.send(prompt.encode("utf-8"))

        while True:
            data = channel.recv(1024)
            if not data:
                break
            buffer += data.decode("utf-8", errors="ignore")
            while "\n" in buffer or "\r" in buffer:
                line, buffer = self._split_line(buffer)
                command = line.strip()
                if not command:
                    channel.send(prompt.encode("utf-8"))
                    continue
                if command in {"exit", "logout", "quit"}:
                    channel.send(b"\n")
                    channel.close()
                    return
                if command in {"conf t", "configure terminal"}:
                    config_mode = True
                    interface_mode = None
                    prompt = f"{self.state.hostname}(config)# "
                    channel.send(b"Enter configuration commands, one per line.\n")
                    channel.send(prompt.encode("utf-8"))
                    continue
                if command == "end":
                    config_mode = False
                    interface_mode = None
                    prompt = f"{self.state.hostname}> "
                    channel.send(prompt.encode("utf-8"))
                    continue

                if config_mode:
                    output, interface_mode, prompt = self._handle_config_command(
                        command, interface_mode
                    )
                else:
                    output = self._handle_exec_command(command)

                if output:
                    channel.send(output.encode("utf-8"))
                channel.send(prompt.encode("utf-8"))

    def _split_line(self, buffer: str) -> tuple[str, str]:
        for sep in ("\r\n", "\n", "\r"):
            if sep in buffer:
                line, rest = buffer.split(sep, 1)
                return line, rest
        return buffer, ""

    def _handle_exec_command(self, command: str) -> str:
        if command.startswith("terminal length"):
            return ""
        if command.startswith("show interfaces status"):
            return self._show_interfaces_status()
        if command.startswith("show cdp neighbors detail"):
            return self._show_cdp_neighbors_detail()
        if command.startswith("show mac address-table"):
            return self._show_mac_address_table()
        if command.startswith("show version"):
            return (
                f"Cisco IOS Software, {self.state.hostname} Version 15.2(2)E\n"
                "Compiled Thu 01-Jan-2015\n\n"
            )
        if command.startswith("show running-config"):
            return self._show_running_config()
        if command.startswith("write memory") or command.startswith("wr mem"):
            return "Building configuration...\n[OK]\n"
        return "% Unrecognized command\n"

    def _handle_config_command(
        self, command: str, interface_mode: str | None
    ) -> tuple[str, str | None, str]:
        prompt = f"{self.state.hostname}(config)# "
        if command.startswith("interface "):
            interface_name = command.split(" ", 1)[1].strip()
            interface_mode = interface_name
            prompt = f"{self.state.hostname}(config-if)# "
            if interface_mode not in self.state.ports:
                self.state.ports[interface_mode] = PortState(interface=interface_mode)
            return "", interface_mode, prompt

        if command == "exit" and interface_mode:
            interface_mode = None
            prompt = f"{self.state.hostname}(config)# "
            return "", interface_mode, prompt

        if interface_mode:
            port = self.state.ports[interface_mode]
            if command.startswith("description "):
                port.description = command.replace("description ", "", 1)
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command.startswith("switchport mode "):
                port.mode = command.split()[-1]
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command.startswith("switchport access vlan "):
                value = command.split()[-1]
                if value.isdigit():
                    port.vlan = int(value)
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command.startswith("speed "):
                port.speed = command.split()[-1]
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command.startswith("duplex "):
                port.duplex = command.split()[-1]
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command == "shutdown":
                port.status = "down"
                port.protocol = "down"
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command == "no shutdown":
                port.status = "up"
                port.protocol = "up"
                return "", interface_mode, f"{self.state.hostname}(config-if)# "
            if command.startswith("switchport port-security"):
                port.has_port_security = True
                return "", interface_mode, f"{self.state.hostname}(config-if)# "

        return "% Invalid command\n", interface_mode, prompt

    def _show_running_config(self) -> str:
        output = [f"hostname {self.state.hostname}", "!"]
        for port in self.state.ports.values():
            output.append(f"interface {port.interface}")
            if port.description:
                output.append(f" description {port.description}")
            if port.mode:
                output.append(f" switchport mode {port.mode}")
            if port.vlan is not None:
                output.append(f" switchport access vlan {port.vlan}")
            if port.speed:
                output.append(f" speed {port.speed}")
            if port.duplex:
                output.append(f" duplex {port.duplex}")
            if port.has_port_security:
                output.append(" switchport port-security")
            if port.status == "down":
                output.append(" shutdown")
            output.append("!")
        output.append("end")
        return "\n".join(output) + "\n"

    def _show_interfaces_status(self) -> str:
        lines = [
            "Port      Name               Status       Vlan       Duplex  Speed Type",
        ]
        for port in self.state.ports.values():
            status = "connected" if port.status == "up" else "notconnect"
            vlan = str(port.vlan) if port.vlan is not None else "1"
            line = f"{port.interface:<9} {port.description[:18]:<18} {status:<11} {vlan:<10} {port.duplex or 'auto':<7} {port.speed or 'auto':<5}"
            lines.append(line)
        return "\n".join(lines) + "\n"

    def _show_cdp_neighbors_detail(self) -> str:
        lines: list[str] = []
        for port in self.state.ports.values():
            if not port.cdp_neighbor:
                continue
            lines.extend(
                [
                    f"Device ID: {port.cdp_neighbor}",
                    f"Interface: {port.interface},  Port ID (outgoing port): {port.interface}",
                    "Platform: cisco WS-C3850, Capabilities: Switch",
                    "",
                ]
            )
        return "\n".join(lines) + "\n"

    def _show_mac_address_table(self) -> str:
        lines = ["Vlan    Mac Address       Type        Ports"]
        for port in self.state.ports.values():
            if port.mac_address:
                mac = port.mac_address.replace(":", ".")
                lines.append(f"{port.vlan or 1:<7} {mac:<17} DYNAMIC     {port.interface}")
        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    config = Path(__file__).resolve().parent / "switch_configs" / "switch_access.json"
    switch = MockSwitch(
        "127.0.0.1",
        2222,
        SwitchState.from_json(config),
        username="admin",
        password="admin",
    )
    switch.start()
    input("Mock switch running. Press Enter to stop.\n")
