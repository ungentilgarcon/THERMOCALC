from html import escape

from app.models.schemas import AdminState


PROVIDER_OPTIONS = [
    {
        "value": "mock",
        "label": "Mock provider",
        "description": "Simulation locale pour preparer les appairages et la topologie sans bridge externe.",
        "supports_physical_pairing": False,
    },
    {
        "value": "zigbee2mqtt",
        "label": "Zigbee2MQTT",
        "description": "Bridge MQTT reel avec discovery sur bridge/devices et permit_join via request/permit_join.",
        "supports_physical_pairing": True,
    },
]

DEVICE_ROLE_OPTIONS = [
    {"value": "thermostat", "label": "Tete thermostatique"},
    {"value": "detector", "label": "Detecteur"},
    {"value": "receiver", "label": "Recepteur"},
]

PAIRING_RELATION_OPTIONS = [
    {"value": "detector-to-receiver", "label": "Detecteur vers recepteur"},
    {"value": "detector-to-thermostat", "label": "Detecteur vers tete thermostatique"},
    {"value": "thermostat-to-receiver", "label": "Tete thermostatique vers recepteur"},
]


def list_provider_options() -> list[dict[str, object]]:
    return PROVIDER_OPTIONS


def list_device_role_options() -> list[dict[str, str]]:
    return DEVICE_ROLE_OPTIONS


def list_pairing_relation_options() -> list[dict[str, str]]:
    return PAIRING_RELATION_OPTIONS


def build_zigbee_overview(state: AdminState) -> list[dict[str, object]]:
    devices_by_controller: dict[str, list[object]] = {}
    pairings_by_controller: dict[str, list[object]] = {}
    for device in state.zigbee_devices:
        devices_by_controller.setdefault(device.controller_id, []).append(device)
    for pairing in state.zigbee_pairings:
        pairings_by_controller.setdefault(pairing.controller_id, []).append(pairing)

    return [
        {
            "controller": controller,
            "devices": sorted(devices_by_controller.get(controller.controller_id, []), key=lambda item: item.device_id.lower()),
            "pairings": sorted(pairings_by_controller.get(controller.controller_id, []), key=lambda item: item.link_id.lower()),
            "topology": build_controller_topology(
                sorted(devices_by_controller.get(controller.controller_id, []), key=lambda item: item.device_id.lower()),
                sorted(pairings_by_controller.get(controller.controller_id, []), key=lambda item: item.link_id.lower()),
            ),
        }
        for controller in state.controllers
    ]


def provider_pairing_notice(provider_type: str, controller_label: str) -> str:
    if provider_type == "zigbee2mqtt":
        return f"Controleur {controller_label}: permit_join Zigbee2MQTT declenchable via MQTT et discovery bridge/devices disponible."
    return f"Controleur {controller_label}: mode appairage logique actif dans le provider mock."


def build_controller_topology(devices: list[object], pairings: list[object]) -> dict[str, object]:
    nodes_by_role = {"detector": [], "thermostat": [], "receiver": []}
    for device in devices:
        nodes_by_role.setdefault(device.role, []).append(device)

    rendered_links = []
    for pairing in pairings:
        rendered_links.append(
            {
                "label": pairing.relation_type,
                "source": pairing.source_device_id,
                "target": pairing.target_device_id,
                "notes": pairing.notes,
            }
        )

    topology = {
        "detectors": nodes_by_role.get("detector", []),
        "thermostats": nodes_by_role.get("thermostat", []),
        "receivers": nodes_by_role.get("receiver", []),
        "links": rendered_links,
    }
    topology["svg"] = build_topology_svg(topology)
    return topology


def build_topology_svg(topology: dict[str, object]) -> str:
    columns = [
        ("Detecteurs", topology.get("detectors", []), 120),
        ("Tetes", topology.get("thermostats", []), 400),
        ("Recepteurs", topology.get("receivers", []), 680),
    ]
    node_positions: dict[str, tuple[int, int]] = {}
    svg_parts = [
        '<svg viewBox="0 0 820 320" class="topology-svg" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Topologie Zigbee">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#17324d"/></marker></defs>',
        '<rect x="0" y="0" width="820" height="320" rx="22" fill="rgba(255,255,255,0.55)" />',
    ]

    for title, devices, x_center in columns:
        svg_parts.append(f'<text x="{x_center}" y="34" text-anchor="middle" font-size="16" font-weight="700" fill="#8f3f20">{escape(title)}</text>')
        for index, device in enumerate(devices):
            y = 70 + index * 78
            x = x_center - 95
            node_positions[device.device_id] = (x_center, y + 24)
            svg_parts.append(f'<rect x="{x}" y="{y}" width="190" height="48" rx="16" fill="#fffaf2" stroke="#d8c3ad"/>')
            svg_parts.append(f'<text x="{x_center}" y="{y + 20}" text-anchor="middle" font-size="13" font-weight="700" fill="#17324d">{escape(device.friendly_name)}</text>')
            svg_parts.append(f'<text x="{x_center}" y="{y + 36}" text-anchor="middle" font-size="11" fill="#58656d">{escape(device.device_id)}</text>')

    for link in topology.get("links", []):
        source = node_positions.get(link["source"])
        target = node_positions.get(link["target"])
        if not source or not target:
            continue
        svg_parts.append(
            f'<path d="M {source[0]} {source[1]} C {(source[0] + target[0]) / 2} {source[1]}, {(source[0] + target[0]) / 2} {target[1]}, {target[0]} {target[1]}" stroke="#17324d" stroke-width="2.2" fill="none" marker-end="url(#arrow)" opacity="0.82"/>'
        )

    svg_parts.append("</svg>")
    return "".join(svg_parts)