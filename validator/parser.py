import re

from .engine import PortConfig


INTERFACE_RE = re.compile(
    r"^(TenGigabitEthernet|GigabitEthernet|FastEthernet|Ethernet|TenGi|Gi|Fa|Te|Et)\S+"
)
CDP_DETAIL_INTERFACE_RE = re.compile(r"Interface: (\S+)")
CDP_DETAIL_DEVICE_RE = re.compile(r"Device ID: (.+)")
MAC_TABLE_RE = re.compile(r"^(\d+)\s+([0-9a-f.]+)\s+\S+\s+(\S+)")


def parse_cli_output(raw_text: str) -> list[PortConfig]:
    ports: dict[str, PortConfig] = {}

    def normalize_interface(name: str) -> str:
        clean = name.strip().rstrip(",;:")
        return (
            clean.replace("TenGigabitEthernet", "Te")
            .replace("GigabitEthernet", "Gi")
            .replace("FastEthernet", "Fa")
            .replace("Ethernet", "Et")
            .replace("TenGi", "Te")
        )

    def get_port(name: str) -> PortConfig:
        short_name = normalize_interface(name)
        if short_name not in ports:
            ports[short_name] = PortConfig(interface=short_name)
        return ports[short_name]

    lines = raw_text.split("\n")

    config_blocks = raw_text.split("interface ")
    for block in config_blocks:
        lines_block = block.split("\n")
        if not lines_block:
            continue
        interface_name = lines_block[0].strip().split(" ")[0]
        if not interface_name:
            continue
        if interface_name.startswith("Vlan"):
            continue
        if not INTERFACE_RE.match(interface_name):
            continue
        port = get_port(interface_name)
        if "shutdown" in block:
            port.status = "down"
            port.protocol = "down"
        for line in lines_block:
            line = line.strip()
            if line.startswith("description "):
                port.description = line.replace("description ", "", 1).strip()
            if line.startswith("switchport access vlan "):
                value = line.split()[-1]
                if value.isdigit():
                    port.vlan = int(value)
            if line.startswith("switchport mode "):
                port.mode = line.split()[-1]
            if line.startswith("speed "):
                port.speed = line.split()[-1]
            if line.startswith("duplex "):
                port.duplex = line.split()[-1]
            if line.startswith("switchport port-security"):
                port.has_port_security = True
        if port.mode == "trunk" and "AP" in port.description:
            port.is_flex_connect = True

    cdp_section = False
    current_cdp_interface: str | None = None
    for line in lines:
        if "Device ID" in line and "Local Intrfce" in line:
            cdp_section = True
            continue
        if cdp_section:
            parts = line.split()
            if not parts:
                continue
            for part in parts:
                if part.startswith(("Gi", "Fa", "Te")):
                    device_id = line.split(part)[0].strip()
                    if device_id:
                        port = get_port(part)
                        port.cdp_neighbor = device_id
                    break

        match_interface = CDP_DETAIL_INTERFACE_RE.search(line)
        if match_interface:
            current_cdp_interface = normalize_interface(match_interface.group(1))
            continue
        match_device = CDP_DETAIL_DEVICE_RE.search(line)
        if match_device and current_cdp_interface:
            port = get_port(current_cdp_interface)
            port.cdp_neighbor = match_device.group(1).strip()
            continue

    for line in lines:
        parts = line.split()
        if len(parts) >= 4:
            if_name = parts[0]
            if INTERFACE_RE.match(if_name):
                status = next(
                    (
                        p
                        for p in parts
                        if p in {"connected", "notconnect", "disabled", "err-disabled"}
                    ),
                    None,
                )
                if status:
                    port = get_port(if_name)
                    if status == "connected":
                        port.status = "up"
                        port.protocol = "up"
                    else:
                        port.status = "down"
                        port.protocol = "down"

        match = MAC_TABLE_RE.match(line.strip())
        if match:
            mac_raw = match.group(2)
            if_name = match.group(3)
            if not INTERFACE_RE.match(if_name):
                continue
            normalized_mac = mac_raw.replace(".", "")
            normalized_mac = ":".join(
                normalized_mac[i : i + 2] for i in range(0, len(normalized_mac), 2)
            )
            port = get_port(if_name)
            port.mac_address = normalized_mac

    return sorted(ports.values(), key=lambda p: p.interface)
