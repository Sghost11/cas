from __future__ import annotations

from typing import Iterable

from django.db import transaction

from devices.models import Device, Port
from netauto.automation import run_playbook
from validator.parser import parse_cli_output


@transaction.atomic
def import_cli_for_device(device: Device, raw_cli: str) -> list[Port]:
    ports = parse_cli_output(raw_cli)
    interfaces = [port.interface for port in ports]
    if interfaces:
        Port.objects.filter(device=device).exclude(interface__in=interfaces).delete()
    saved: list[Port] = []
    for port_config in ports:
        defaults = {
            "status": port_config.status,
            "protocol": port_config.protocol,
            "vlan": port_config.vlan,
            "mode": port_config.mode,
            "description": port_config.description,
            "speed": port_config.speed,
            "duplex": port_config.duplex,
            "mac_address": port_config.mac_address,
            "cdp_neighbor": port_config.cdp_neighbor,
            "has_port_security": port_config.has_port_security,
        }
        saved_port, _created = Port.objects.update_or_create(
            device=device,
            interface=port_config.interface,
            defaults=defaults,
        )
        saved.append(saved_port)
    return saved


def serialize_ports(ports: Iterable[Port]) -> list[dict[str, str]]:
    payload = []
    for port in ports:
        payload.append(
            {
                "interface": port.interface,
                "status": port.status,
                "protocol": port.protocol,
                "vlan": port.vlan,
                "mode": port.mode,
                "description": port.description,
                "speed": port.speed,
                "duplex": port.duplex,
                "mac_address": port.mac_address,
                "cdp_neighbor": port.cdp_neighbor,
                "has_port_security": port.has_port_security,
                "validation_action": port.validation_action,
                "validation_reason": port.validation_reason,
                "validation_category": port.validation_category,
                "last_change_request_id": port.last_change_request_id,
                "last_change_approved_by": port.last_change_approved_by,
                "last_change_approved_at": port.last_change_approved_at,
            }
        )
    return payload


def apply_validation_to_ports(device: Device) -> list[Port]:
    from validator.engine import PortConfig, ValidationResult, analyze_port

    ports = Port.objects.filter(device=device)
    updated_ports: list[Port] = []
    site_name = device.site.name if device.site else ""
    for port in ports:
        port_config = PortConfig(
            interface=port.interface,
            status=port.status,
            protocol=port.protocol,
            description=port.description,
            mac_address=port.mac_address,
            cdp_neighbor=port.cdp_neighbor,
            vlan=port.vlan,
            mode=port.mode,
            has_port_security=port.has_port_security,
            speed=port.speed,
            duplex=port.duplex,
        )
        result = analyze_port(port_config, site_name)
        if port.mode == "access" and port.vlan and result.action == "MIGRAR":
            if port.last_change_request_id:
                result = ValidationResult(
                    action="YA_MIGRADO",
                    reason="Puerto ya configurado como acceso.",
                    category="Estado",
                )
        port.validation_action = result.action
        port.validation_reason = result.reason
        port.validation_category = result.category
        port.save(
            update_fields=[
                "validation_action",
                "validation_reason",
                "validation_category",
                "updated_at",
            ]
        )
        updated_ports.append(port)
    return updated_ports


def import_cli_file_for_device(device: Device, path: str) -> list[Port]:
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        raw_cli = handle.read()
    return import_cli_for_device(device, raw_cli)


def sync_device(device: Device) -> tuple[dict, list[Port]]:
    result = run_playbook(
        playbook="gather_port_config.yml",
        extra_vars={},
        device_ip=device.ip,
        limit=device.hostname or device.ip,
    )
    cli_path = f"/tmp/{device.hostname}-cli.txt"
    ports: list[Port] = []
    if result.get("rc") == 0:
        try:
            ports = import_cli_file_for_device(device, cli_path)
            ports = apply_validation_to_ports(device)
        except FileNotFoundError:
            ports = []
    return result, ports
