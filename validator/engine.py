from dataclasses import dataclass


@dataclass
class PortConfig:
    interface: str
    status: str = ""
    protocol: str = ""
    description: str = ""
    mac_address: str = ""
    cdp_neighbor: str = ""
    vlan: int | None = None
    mode: str = ""
    vendor: str = "Cisco"
    has_port_security: bool = False
    speed: str = ""
    duplex: str = ""
    is_flex_connect: bool = False


@dataclass
class ValidationResult:
    action: str
    reason: str
    category: str


BIOMEDICAL_MACS = {"00:11:22:33:44:55", "AA:BB:CC:DD:EE:FF"}
LOCAL_CONTROLLER_SITES = {"SEDE_NORTE", "SEDE_CENTRO"}
DOCUMENTED_EXCLUDE_VLANS = {25, 123}

ACTION_TEMPLATE_MAP = {
    "MIGRAR": "STANDARD_8021X",
    "EXCLUIR": "NO_ACTION",
    "YA_MIGRADO": "NO_ACTION",
    "REVISAR": "NO_ACTION",
    "ERROR": "NO_ACTION",
}


def analyze_port(port: PortConfig, site_name: str) -> ValidationResult:
    if port.interface in {"Gi0/0", "GigabitEthernet0/0"}:
        return ValidationResult(
            action="EXCLUIR",
            reason="Puerto de gestion del equipo.",
            category="Infraestructura",
        )

    if port.vendor and port.vendor != "Cisco":
        return ValidationResult(
            action="ERROR",
            reason="Solo soportamos automatizacion en Cisco IOS.",
            category="Soporte",
        )

    if port.cdp_neighbor and ("Switch" in port.cdp_neighbor or "Router" in port.cdp_neighbor):
        return ValidationResult(
            action="EXCLUIR",
            reason="Enlace critico hacia Core o Distribucion.",
            category="Infraestructura",
        )

    if port.mode == "trunk":
        return ValidationResult(
            action="EXCLUIR",
            reason="Puerto en trunk: requiere exclusion de 802.1X.",
            category="Infraestructura",
        )

    if port.vlan == 123 or "COBAS" in port.description or "CAMARA" in port.description:
        return ValidationResult(
            action="EXCLUIR",
            reason="Red de terceros (CCTV/Control Acceso).",
            category="Seguridad",
        )

    if port.vlan in DOCUMENTED_EXCLUDE_VLANS:
        return ValidationResult(
            action="EXCLUIR",
            reason="VLAN documentada como exclusion.",
            category="Politica",
        )

    if port.vlan == 3 and port.has_port_security:
        return ValidationResult(
            action="EXCLUIR",
            reason="Servidores criticos con MAC Sticky.",
            category="Servidores",
        )

    if port.vlan == 12 and port.speed == "100" and port.duplex == "full":
        return ValidationResult(
            action="EXCLUIR",
            reason="Plantas telefonicas antiguas (falla negociacion).",
            category="Legacy",
        )

    if port.vlan == 25:
        return ValidationResult(
            action="EXCLUIR",
            reason="VLAN dedicada a equipos vitales.",
            category="Biomedico",
        )

    if port.mac_address and port.mac_address in BIOMEDICAL_MACS:
        return ValidationResult(
            action="EXCLUIR",
            reason="Inventario de equipos biomedicos.",
            category="Biomedico",
        )

    if port.status == "up" and port.protocol == "down":
        return ValidationResult(
            action="REVISAR",
            reason="Posible equipo medico silencioso conectado.",
            category="Biomedico",
        )

    if port.description and port.status == "down" and not port.cdp_neighbor:
        return ValidationResult(
            action="MIGRAR",
            reason="Ghost Port: Equipo retirado, puerto sucio.",
            category="Limpieza",
        )

    if port.mode == "access" and port.vlan and port.vlan not in DOCUMENTED_EXCLUDE_VLANS:
        return ValidationResult(
            action="MIGRAR",
            reason="VLAN no documentada para exclusion: candidato a migracion.",
            category="Politica",
        )

    return ValidationResult(
        action="MIGRAR",
        reason="Puerto de usuario estandar (PC/Laptop/Telefono).",
        category="Usuario",
    )
