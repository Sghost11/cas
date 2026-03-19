from jinja2 import Template


TEMPLATES = {
    "STANDARD_8021X": """
interface {{ interface }}
 description {{ description }}
 switchport mode access
 switchport access vlan {{ vlan }}
 spanning-tree portfast
 authentication port-control auto
end
""".strip(),
    "BIOMEDICAL": """
interface {{ interface }}
 description {{ description }}
 switchport mode access
 switchport access vlan 25
 spanning-tree portfast
end
""".strip(),
    "INFRA_TRUNK": """
interface {{ interface }}
 description {{ description }}
 switchport mode trunk
 spanning-tree portfast trunk
end
""".strip(),
}


def generate_config(template_name: str, data: dict[str, str | int]) -> str:
    if template_name in {"NO_ACTION", "EXCLUIR", "YA_MIGRADO", "REVISAR", "ERROR"}:
        return ""
    if template_name not in TEMPLATES:
        raise ValueError(f"Unknown template: {template_name}")
    template = Template(TEMPLATES[template_name])
    return template.render(**data)
