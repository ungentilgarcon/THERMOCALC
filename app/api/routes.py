import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import (
    BILLING_ECS_WEIGHT,
    BILLING_HEATING_WEIGHT,
    DEFAULT_AUTO_DISCOVERY_ENABLED,
    DEFAULT_DISCOVERY_INTERVAL_MINUTES,
    DEFAULT_PERMIT_JOIN_SECONDS,
    DEFAULT_ZIGBEE2MQTT_BASE_TOPIC,
    DEFAULT_ZIGBEE2MQTT_CONTROLLER_ID,
    DEFAULT_ZIGBEE2MQTT_CONTROLLER_LABEL,
    DEFAULT_ZIGBEE2MQTT_PASSWORD,
    DEFAULT_ZIGBEE2MQTT_URL,
    DEFAULT_ZIGBEE2MQTT_USERNAME,
    GENERATED_REPORTS_DIR,
    SAMPLE_DATA_PATH,
)
from app.models.schemas import AllocationInput
from app.services.archives import delete_archive, export_archives_zip, list_archive_records, rename_archive
from app.services.admin_state import (
    add_or_update_quick_profile,
    add_or_update_controller,
    add_or_update_thermostat_schedule,
    add_or_update_thermostat,
    add_or_update_zigbee_device,
    add_or_update_zigbee_pairing,
    add_occupant,
    apply_assignments_to_payload,
    build_schedule_payload_from_profile,
    clear_thermostat_override,
    clear_occupant_overrides,
    create_schedules_for_days,
    ensure_ecs_readings_for_occupants,
    load_admin_state,
    remove_controller,
    remove_occupant,
    remove_quick_profile,
    remove_thermostat_schedule,
    remove_thermostat,
    remove_zigbee_device,
    remove_zigbee_pairing,
    set_occupant_hors_gel,
    set_thermostat_override,
    select_ecs_allocation_for_period,
    update_ecs_readings_and_allocate,
    update_schedule,
)
from app.services.auth import ensure_admin, is_admin_authenticated, login_admin, logout_admin
from app.services.billing import build_combined_allocation_rows
from app.services.consumption import build_monthly_allocation
from app.services.reporting import build_monthly_pdf
from app.services.runtime_measurements import build_realtime_payload, build_trv26_telemetry
from app.services.scheduler import run_scheduled_generation_once
from app.services.thermostat_control import WEEKDAY_LABELS, apply_active_thermostat_controls
from app.services.test_scenarios import (
    build_ecs_rows,
    build_empty_payload,
    build_rows,
    build_test_ecs_allocation,
    build_test_payload,
    list_test_scenarios,
)
from app.services.zigbee import (
    build_zigbee_overview,
    list_device_role_options,
    list_pairing_relation_options,
    list_provider_options,
    provider_pairing_notice,
)
from app.services.zigbee2mqtt import prepare_new_thermostat_pairing, refresh_controller_inventory, test_broker_connectivity

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@dataclass(frozen=True)
class PayloadSource:
    code: str
    label: str
    detail: str
    tone: str


def load_payload_with_source() -> tuple[AllocationInput, PayloadSource]:
    admin_state = load_admin_state()
    realtime_payload = build_realtime_payload(admin_state)
    if realtime_payload is not None:
        return realtime_payload, PayloadSource(
            code="mqtt",
            label="MQTT temps reel",
            detail="Calcul base sur les dernieres mesures TRV26 remontees par Zigbee2MQTT.",
            tone="live",
        )
    content = json.loads(Path(SAMPLE_DATA_PATH).read_text(encoding="utf-8"))
    payload = AllocationInput.model_validate(content)
    return apply_assignments_to_payload(payload, admin_state), PayloadSource(
        code="json",
        label="JSON de test",
        detail="Calcul base sur le jeu JSON de test local, utilise tant que les mesures MQTT ne couvrent pas encore le besoin.",
        tone="fallback",
    )


def load_sample_payload() -> AllocationInput:
    return load_payload_with_source()[0]


def admin_redirect(notice: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin?notice={quote_plus(notice)}", status_code=303)


def admin_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=303)


def ecs_redirect(notice: str) -> RedirectResponse:
    return RedirectResponse(url=f"/ecs?notice={quote_plus(notice)}", status_code=303)


def test_calculations_redirect(notice: str = "") -> RedirectResponse:
    suffix = f"?notice={quote_plus(notice)}" if notice else ""
    return RedirectResponse(url=f"/test-calculs{suffix}", status_code=303)


def test_consumption_redirect(notice: str = "") -> RedirectResponse:
    suffix = f"?notice={quote_plus(notice)}" if notice else ""
    return RedirectResponse(url=f"/test-consommation{suffix}", status_code=303)


def heating_control_redirect(notice: str = "") -> RedirectResponse:
    suffix = f"?notice={quote_plus(notice)}" if notice else ""
    return RedirectResponse(url=f"/pilotage-chauffage{suffix}", status_code=303)


def sanitize_filename(filename: str) -> str:
    return Path(filename).name


def build_heating_control_view(admin_state) -> list[dict[str, object]]:
    overrides_by_trv = {item.trv_id.lower(): item for item in admin_state.thermostat_overrides}
    control_states_by_trv = {item.trv_id.lower(): item for item in admin_state.thermostat_control_states}
    grouped: list[dict[str, object]] = []
    for occupant in admin_state.occupants:
        thermostats = []
        assignments = [item for item in admin_state.thermostats if item.owner_name.lower() == occupant.owner_name.lower()]
        for assignment in assignments:
            thermostats.append(
                {
                    "assignment": assignment,
                    "schedules": [
                        item
                        for item in admin_state.thermostat_schedules
                        if item.trv_id.lower() == assignment.trv_id.lower()
                    ],
                    "override": overrides_by_trv.get(assignment.trv_id.lower()),
                    "control_state": control_states_by_trv.get(assignment.trv_id.lower()),
                }
            )
        occupant_overrides = [item["override"] for item in thermostats if item["override"] is not None]
        has_hors_gel = any(item.mode == "hors-gel" for item in occupant_overrides)
        has_temporary_override = any(item.mode != "hors-gel" for item in occupant_overrides)
        if has_hors_gel and has_temporary_override:
            occupant_status_label = "Vacances + overrides"
            occupant_status_class = "status-occupant-mixed"
        elif has_hors_gel:
            occupant_status_label = "Mode vacances hors-gel"
            occupant_status_class = "status-occupant-freeze"
        elif has_temporary_override:
            occupant_status_label = "Override temporaire"
            occupant_status_class = "status-occupant-temporary"
        else:
            occupant_status_label = "Planning seul"
            occupant_status_class = "status-occupant-planning"
        grouped.append(
            {
                "occupant": occupant,
                "thermostats": thermostats,
                "has_override": any(item["override"] is not None for item in thermostats),
                "occupant_status_label": occupant_status_label,
                "occupant_status_class": occupant_status_class,
            }
        )
    return grouped


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    payload, payload_source = load_payload_with_source()
    report = build_monthly_allocation(payload)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"report": report, "payload_source": payload_source},
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    notice: str = "",
    start_month: str = Query(default=""),
    end_month: str = Query(default=""),
    owner_name: str = Query(default=""),
) -> Response:
    if not is_admin_authenticated(request):
        return admin_login_redirect()
    admin_state = load_admin_state()
    payload, payload_source = load_payload_with_source()
    report = build_monthly_allocation(payload)
    archive_records = list_archive_records(
        start_month=start_month or None,
        end_month=end_month or None,
        owner_name=owner_name or None,
    )
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "admin_state": admin_state,
            "report": report,
            "notice": notice,
            "generated_reports": archive_records,
            "archive_filters": {
                "start_month": start_month,
                "end_month": end_month,
                "owner_name": owner_name,
            },
            "provider_options": list_provider_options(),
            "device_role_options": list_device_role_options(),
            "pairing_relation_options": list_pairing_relation_options(),
            "payload_source": payload_source,
            "trv26_telemetry": build_trv26_telemetry(admin_state),
            "zigbee_overview": build_zigbee_overview(admin_state),
            "config_defaults": {
                "controller_id": DEFAULT_ZIGBEE2MQTT_CONTROLLER_ID,
                "controller_label": DEFAULT_ZIGBEE2MQTT_CONTROLLER_LABEL,
                "mqtt_url": DEFAULT_ZIGBEE2MQTT_URL,
                "mqtt_username": DEFAULT_ZIGBEE2MQTT_USERNAME,
                "mqtt_password": DEFAULT_ZIGBEE2MQTT_PASSWORD,
                "base_topic": DEFAULT_ZIGBEE2MQTT_BASE_TOPIC,
                "auto_discovery_enabled": DEFAULT_AUTO_DISCOVERY_ENABLED,
                "discovery_interval_minutes": DEFAULT_DISCOVERY_INTERVAL_MINUTES,
                "permit_join_seconds": DEFAULT_PERMIT_JOIN_SECONDS,
                "billing_heating_weight": BILLING_HEATING_WEIGHT,
                "billing_ecs_weight": BILLING_ECS_WEIGHT,
            },
        },
    )


@router.get("/ecs", response_class=HTMLResponse)
def ecs_page(request: Request, notice: str = "") -> Response:
    if not is_admin_authenticated(request):
        return admin_login_redirect()
    admin_state = ensure_ecs_readings_for_occupants(load_admin_state())
    return templates.TemplateResponse(
        request=request,
        name="ecs.html",
        context={
            "notice": notice,
            "admin_state": admin_state,
            "ecs_readings": admin_state.ecs_readings,
            "last_ecs_allocation": admin_state.last_ecs_allocation,
            "ecs_allocation_history": admin_state.ecs_allocation_history,
        },
    )


@router.get("/pilotage-chauffage", response_class=HTMLResponse)
def heating_control_page(request: Request, notice: str = "") -> Response:
    if not is_admin_authenticated(request):
        return admin_login_redirect()
    admin_state = load_admin_state()
    return templates.TemplateResponse(
        request=request,
        name="heating_control.html",
        context={
            "notice": notice,
            "admin_state": admin_state,
            "weekday_options": [{"value": index, "label": label} for index, label in enumerate(WEEKDAY_LABELS)],
            "quick_profiles": admin_state.thermostat_quick_profiles,
            "heating_groups": build_heating_control_view(admin_state),
        },
    )


@router.get("/test-calculs", response_class=HTMLResponse)
def test_calculations_page(
    request: Request,
    notice: str = "",
    scenario: str = Query(default="balanced"),
    rows: int = Query(default=4),
) -> Response:
    if not is_admin_authenticated(request):
        return admin_login_redirect()
    available_scenarios = list_test_scenarios()
    scenario_keys = {item["key"] for item in available_scenarios}
    if scenario == "manual":
        payload = build_empty_payload(rows)
    else:
        payload = build_test_payload(scenario if scenario in scenario_keys else "balanced")
    return templates.TemplateResponse(
        request=request,
        name="test_calculs.html",
        context={
            "notice": notice,
            "selected_scenario": scenario if scenario in scenario_keys or scenario == "manual" else "balanced",
            "scenario_options": available_scenarios,
            "rows": build_rows(payload),
            "month_label": payload.month_label,
            "row_count": len(payload.samples),
            "report": None,
        },
    )


@router.get("/test-consommation", response_class=HTMLResponse)
def test_consumption_page(
    request: Request,
    notice: str = "",
    scenario: str = Query(default="balanced"),
    rows: int = Query(default=4),
) -> Response:
    if not is_admin_authenticated(request):
        return admin_login_redirect()
    available_scenarios = list_test_scenarios()
    scenario_keys = {item["key"] for item in available_scenarios}
    selected_scenario = scenario if scenario in scenario_keys or scenario == "manual" else "balanced"
    if selected_scenario == "manual":
        payload = build_empty_payload(rows)
    else:
        payload = build_test_payload(selected_scenario)
    return templates.TemplateResponse(
        request=request,
        name="test_consommation.html",
        context={
            "notice": notice,
            "selected_scenario": selected_scenario,
            "scenario_options": available_scenarios,
            "rows": build_rows(payload),
            "ecs_rows": build_ecs_rows(payload, scenario_key=selected_scenario),
            "month_label": payload.month_label,
            "row_count": len(payload.samples),
            "total_bill_amount": 180.0,
            "bill_amount_label": "EUR",
            "report": None,
            "ecs_allocation": None,
            "combined_rows": None,
        },
    )


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, error: str = "") -> Response:
    if is_admin_authenticated(request):
        return admin_redirect("Session deja ouverte")
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={"error": error},
    )


@router.post("/admin/login")
def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    if login_admin(request, username=username, password=password):
        return admin_redirect("Connexion admin active")
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={"error": "Identifiants invalides"},
        status_code=401,
    )


@router.post("/admin/logout")
def admin_logout(request: Request) -> RedirectResponse:
    logout_admin(request)
    return admin_login_redirect()


@router.post("/admin/occupants")
def create_occupant(request: Request, owner_name: str = Form(...), notes: str = Form(default="")) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    add_occupant(owner_name=owner_name, notes=notes)
    return admin_redirect("Occupant enregistre")


@router.post("/admin/controllers")
def create_controller(
    request: Request,
    controller_id: str = Form(...),
    label: str = Form(...),
    provider_type: str = Form(...),
    endpoint_url: str = Form(default=""),
    mqtt_username: str = Form(default=""),
    mqtt_password: str = Form(default=""),
    base_topic: str = Form(default="zigbee2mqtt"),
    auto_discovery_enabled: str | None = Form(default=None),
    discovery_interval_minutes: int = Form(default=15),
    notes: str = Form(default=""),
    enabled: str | None = Form(default=None),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    add_or_update_controller(
        controller_id=controller_id,
        label=label,
        provider_type=provider_type,
        endpoint_url=endpoint_url,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        base_topic=base_topic,
        auto_discovery_enabled=auto_discovery_enabled == "on",
        discovery_interval_minutes=discovery_interval_minutes,
        notes=notes,
        enabled=enabled == "on",
    )
    return admin_redirect("Controleur Zigbee enregistre")


@router.post("/admin/controllers/delete")
def delete_controller(request: Request, controller_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_controller(controller_id)
    return admin_redirect("Controleur Zigbee supprime")


@router.post("/admin/controllers/pairing-mode")
def request_controller_pairing_mode(
    request: Request,
    controller_id: str = Form(...),
    duration_seconds: int = Form(default=60),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    state = load_admin_state()
    controller = next((item for item in state.controllers if item.controller_id == controller_id), None)
    if controller is None:
        return admin_redirect("Controleur introuvable")
    if controller.provider_type == "zigbee2mqtt":
        try:
            message = prepare_new_thermostat_pairing(controller, duration_seconds=duration_seconds)
            return admin_redirect(f"{message} sur {controller.label}")
        except Exception as exc:
            return admin_redirect(f"Echec permit join: {exc}")
    return admin_redirect(provider_pairing_notice(controller.provider_type, controller.label))


@router.post("/admin/controllers/connectivity-test")
def controller_connectivity_test(request: Request, controller_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    state = load_admin_state()
    controller = next((item for item in state.controllers if item.controller_id == controller_id), None)
    if controller is None:
        return admin_redirect("Controleur introuvable")
    success, message = test_broker_connectivity(controller)
    prefix = "Connectivite OK" if success else "Connectivite KO"
    return admin_redirect(f"{prefix}: {message}")


@router.post("/admin/controllers/pair-new-thermostat")
def pair_new_thermostat(
    request: Request,
    controller_id: str = Form(...),
    expected_device_id: str = Form(default=""),
    friendly_name: str = Form(default=""),
    owner_name: str = Form(default=""),
    zone_label: str = Form(default=""),
    surface_m2: float | None = Form(default=None),
    duration_seconds: int = Form(default=60),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    state = load_admin_state()
    controller = next((item for item in state.controllers if item.controller_id == controller_id), None)
    if controller is None:
        return admin_redirect("Controleur introuvable")
    if controller.provider_type != "zigbee2mqtt":
        return admin_redirect("L'appairage des nouvelles tetes est disponible uniquement pour zigbee2mqtt")
    try:
        message = prepare_new_thermostat_pairing(
            controller=controller,
            duration_seconds=duration_seconds,
            expected_device_id=expected_device_id,
            friendly_name=friendly_name,
            owner_name=owner_name,
            zone_label=zone_label,
            surface_m2=surface_m2,
        )
        return admin_redirect(message)
    except Exception as exc:
        return admin_redirect(f"Echec appairage tete: {exc}")


@router.post("/admin/controllers/discover")
def discover_controller_devices(request: Request, controller_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    state = load_admin_state()
    controller = next((item for item in state.controllers if item.controller_id == controller_id), None)
    if controller is None:
        return admin_redirect("Controleur introuvable")
    if controller.provider_type != "zigbee2mqtt":
        return admin_redirect("Discovery distante disponible uniquement pour zigbee2mqtt")
    try:
        count, status = refresh_controller_inventory(controller)
        return admin_redirect(f"{status} sur {controller.label}")
    except Exception as exc:
        return admin_redirect(f"Echec discovery: {exc}")


@router.post("/admin/thermostats")
def create_thermostat(
    request: Request,
    trv_id: str = Form(...),
    zone_label: str = Form(...),
    owner_name: str = Form(...),
    surface_m2: float = Form(...),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    add_or_update_thermostat(
        trv_id=trv_id,
        zone_label=zone_label,
        owner_name=owner_name,
        surface_m2=surface_m2,
    )
    return admin_redirect("Tete thermostatique enregistree")


@router.post("/admin/zigbee/devices")
def create_zigbee_device(
    request: Request,
    device_id: str = Form(...),
    controller_id: str = Form(...),
    role: str = Form(...),
    friendly_name: str = Form(...),
    model: str = Form(default=""),
    ieee_address: str = Form(default=""),
    owner_name: str = Form(default=""),
    zone_label: str = Form(default=""),
    surface_m2: float | None = Form(default=None),
    enabled: str | None = Form(default=None),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    add_or_update_zigbee_device(
        device_id=device_id,
        controller_id=controller_id,
        role=role,
        friendly_name=friendly_name,
        model=model,
        ieee_address=ieee_address,
        owner_name=owner_name,
        zone_label=zone_label,
        surface_m2=surface_m2,
        enabled=enabled == "on",
    )
    return admin_redirect("Device Zigbee enregistre")


@router.post("/admin/zigbee/devices/delete")
def delete_zigbee_device(request: Request, device_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_zigbee_device(device_id)
    return admin_redirect("Device Zigbee supprime")


@router.post("/admin/zigbee/pairings")
def create_zigbee_pairing(
    request: Request,
    link_id: str = Form(...),
    controller_id: str = Form(...),
    source_device_id: str = Form(...),
    target_device_id: str = Form(...),
    relation_type: str = Form(...),
    notes: str = Form(default=""),
    enabled: str | None = Form(default=None),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    add_or_update_zigbee_pairing(
        link_id=link_id,
        controller_id=controller_id,
        source_device_id=source_device_id,
        target_device_id=target_device_id,
        relation_type=relation_type,
        notes=notes,
        enabled=enabled == "on",
    )
    return admin_redirect("Lien d'appairage enregistre")


@router.post("/admin/zigbee/pairings/delete")
def delete_zigbee_pairing(request: Request, link_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_zigbee_pairing(link_id)
    return admin_redirect("Lien d'appairage supprime")


@router.post("/admin/occupants/delete")
def delete_occupant(request: Request, owner_name: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_occupant(owner_name)
    return admin_redirect("Occupant supprime")


@router.post("/admin/thermostats/delete")
def delete_thermostat(request: Request, trv_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_thermostat(trv_id)
    return admin_redirect("Tete thermostatique supprimee")


@router.post("/admin/schedule")
def update_pdf_schedule(
    request: Request,
    enabled: str | None = Form(default=None),
    day_of_month: int = Form(...),
    hour: int = Form(...),
    minute: int = Form(...),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    update_schedule(
        enabled=enabled == "on",
        day_of_month=day_of_month,
        hour=hour,
        minute=minute,
    )
    return admin_redirect("Planification PDF mise a jour")


@router.post("/pilotage-chauffage/profils")
def create_quick_profile(
    request: Request,
    profile_id: str = Form(default=""),
    profile_name: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    target_temperature_c: float = Form(...),
    enabled: str | None = Form(default=None),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    try:
        add_or_update_quick_profile(
            profile_id=profile_id,
            profile_name=profile_name,
            start_time=start_time,
            end_time=end_time,
            target_temperature_c=target_temperature_c,
            enabled=enabled == "on",
        )
    except ValueError as exc:
        return heating_control_redirect(str(exc))
    return heating_control_redirect("Profil rapide enregistre")


@router.post("/pilotage-chauffage/profils/delete")
def delete_quick_profile(request: Request, profile_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_quick_profile(profile_id)
    return heating_control_redirect("Profil rapide supprime")


@router.post("/pilotage-chauffage/plannings")
async def create_heating_schedule(request: Request) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    trv_id = str(form.get("trv_id", "")).strip()
    profile_id = str(form.get("profile_id", "")).strip()
    start_time = str(form.get("start_time", "")).strip()
    end_time = str(form.get("end_time", "")).strip()
    try:
        target_temperature_c = float(str(form.get("target_temperature_c", "20")).strip() or "20")
        primary_weekday = int(str(form.get("weekday", "0")).strip() or "0")
        copy_weekdays = [int(value) for value in form.getlist("copy_weekdays") if str(value).strip() != ""]
    except ValueError:
        return heating_control_redirect("Valeurs invalides dans le planning chauffage")
    enabled = str(form.get("enabled", "")).strip() == "on"
    weekdays = [primary_weekday, *copy_weekdays]
    profile_name = ""
    try:
        if profile_id:
            profile = build_schedule_payload_from_profile(profile_id)
            start_time = profile.start_time
            end_time = profile.end_time
            target_temperature_c = profile.target_temperature_c
            enabled = profile.enabled
            profile_name = profile.profile_name
        create_schedules_for_days(
            trv_id=trv_id,
            weekdays=weekdays,
            start_time=start_time,
            end_time=end_time,
            target_temperature_c=target_temperature_c,
            profile_name=profile_name,
            enabled=enabled,
        )
    except ValueError as exc:
        return heating_control_redirect(str(exc))
    if len(set(weekdays)) > 1:
        return heating_control_redirect("Creneaux dupliques sur plusieurs jours")
    return heating_control_redirect("Creneau de chauffe enregistre")


@router.post("/pilotage-chauffage/plannings/delete")
def delete_heating_schedule(request: Request, schedule_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    remove_thermostat_schedule(schedule_id)
    return heating_control_redirect("Creneau de chauffe supprime")


@router.post("/pilotage-chauffage/override")
def create_heating_override(
    request: Request,
    trv_id: str = Form(...),
    target_temperature_c: float = Form(...),
    duration_hours: int = Form(...),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    try:
        set_thermostat_override(
            trv_id=trv_id,
            target_temperature_c=target_temperature_c,
            duration_hours=duration_hours,
        )
        apply_active_thermostat_controls(trv_filter=trv_id)
    except ValueError as exc:
        return heating_control_redirect(str(exc))
    return heating_control_redirect("Override temporaire active")


@router.post("/pilotage-chauffage/override/delete")
def delete_heating_override(request: Request, trv_id: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    clear_thermostat_override(trv_id)
    return heating_control_redirect("Override supprime")


@router.post("/pilotage-chauffage/occupants/apply")
def apply_occupant_planning_now(request: Request, owner_name: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    applied = apply_active_thermostat_controls(owner_filter=owner_name)
    if not applied:
        return heating_control_redirect("Aucune consigne active a appliquer pour cet occupant")
    return heating_control_redirect(f"Consignes appliquees sur {len(applied)} tete(s)")


@router.post("/pilotage-chauffage/occupants/hors-gel")
def enable_occupant_hors_gel(request: Request, owner_name: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    try:
        set_occupant_hors_gel(owner_name)
        apply_active_thermostat_controls(owner_filter=owner_name)
    except ValueError as exc:
        return heating_control_redirect(str(exc))
    return heating_control_redirect("Hors-gel actif pour cet occupant")


@router.post("/pilotage-chauffage/occupants/hors-gel/delete")
def disable_occupant_hors_gel(request: Request, owner_name: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    clear_occupant_overrides(owner_name)
    return heating_control_redirect("Overrides occupant supprimes")


@router.post("/admin/reports/generate")
def generate_pdf_now(request: Request) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    report = build_monthly_allocation(load_sample_payload())
    output_path = GENERATED_REPORTS_DIR / f"thermocalc-{report.month_label}.pdf"
    output_file = run_scheduled_generation_once(report=report, force=True, output_path=output_path)
    return admin_redirect(f"PDF genere: {output_file.name}")


@router.post("/test-calculs")
async def run_test_calculations(request: Request) -> Response:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    month_label = str(form.get("month_label", "Scenario manuel")).strip() or "Scenario manuel"
    scenario = str(form.get("scenario", "manual")).strip() or "manual"
    trv_ids = form.getlist("trv_id")
    zone_labels = form.getlist("zone_label")
    owner_names = form.getlist("owner_name")
    surface_values = form.getlist("surface_m2")
    target_values = form.getlist("target_temperature_c")
    current_values = form.getlist("current_temperature_c")
    valve_values = form.getlist("valve_open_percent")
    running_states = form.getlist("running_state")
    duty_values = form.getlist("duty_cycle_percent")

    samples = []
    row_total = max(
        len(trv_ids),
        len(zone_labels),
        len(owner_names),
        len(surface_values),
        len(target_values),
        len(current_values),
        len(valve_values),
        len(running_states),
        len(duty_values),
    )
    for index in range(row_total):
        trv_id = str(trv_ids[index] if index < len(trv_ids) else "").strip()
        zone_label = str(zone_labels[index] if index < len(zone_labels) else "").strip()
        owner_name = str(owner_names[index] if index < len(owner_names) else "").strip()
        if not any([trv_id, zone_label, owner_name]):
            continue
        try:
            surface_m2 = float(surface_values[index])
            target_temperature_c = float(target_values[index])
            current_temperature_c = float(current_values[index])
            valve_open_percent = float(valve_values[index])
            duty_value = str(duty_values[index] if index < len(duty_values) else "").strip()
            duty_cycle_percent = float(duty_value) if duty_value else None
        except (TypeError, ValueError):
            return test_calculations_redirect("Valeurs numeriques invalides dans le scenario de test")
        samples.append(
            {
                "trv_id": trv_id or f"scenario-{index + 1}",
                "zone_label": zone_label or f"Zone {index + 1}",
                "owner_name": owner_name or f"Occupant {index + 1}",
                "surface_m2": surface_m2,
                "target_temperature_c": target_temperature_c,
                "current_temperature_c": current_temperature_c,
                "valve_open_percent": valve_open_percent,
                "running_state": str(running_states[index] if index < len(running_states) else "unknown").strip(),
                "duty_cycle_percent": duty_cycle_percent,
                "captured_at": "2026-03-11T08:00:00Z",
            }
        )

    if not samples:
        return test_calculations_redirect("Ajoute au moins une ligne de chauffe pour lancer le test")

    payload = AllocationInput.model_validate({"month_label": month_label, "samples": samples})
    report = build_monthly_allocation(payload)
    return templates.TemplateResponse(
        request=request,
        name="test_calculs.html",
        context={
            "notice": "Scenario calcule en mode test. Aucun etat persistant n'a ete modifie.",
            "selected_scenario": scenario,
            "scenario_options": list_test_scenarios(),
            "rows": build_rows(payload),
            "month_label": payload.month_label,
            "row_count": len(payload.samples),
            "report": report,
        },
    )


@router.post("/test-consommation")
async def run_test_consumption(request: Request) -> Response:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    month_label = str(form.get("month_label", "Scenario consommation")).strip() or "Scenario consommation"
    scenario = str(form.get("scenario", "manual")).strip() or "manual"
    trv_ids = form.getlist("trv_id")
    zone_labels = form.getlist("zone_label")
    owner_names = form.getlist("owner_name")
    surface_values = form.getlist("surface_m2")
    target_values = form.getlist("target_temperature_c")
    current_values = form.getlist("current_temperature_c")
    valve_values = form.getlist("valve_open_percent")
    running_states = form.getlist("running_state")
    duty_values = form.getlist("duty_cycle_percent")
    ecs_owner_names = form.getlist("ecs_owner_name")
    ecs_delta_values = form.getlist("ecs_delta_m3")

    samples = []
    row_total = max(
        len(trv_ids),
        len(zone_labels),
        len(owner_names),
        len(surface_values),
        len(target_values),
        len(current_values),
        len(valve_values),
        len(running_states),
        len(duty_values),
    )
    for index in range(row_total):
        trv_id = str(trv_ids[index] if index < len(trv_ids) else "").strip()
        zone_label = str(zone_labels[index] if index < len(zone_labels) else "").strip()
        owner_name = str(owner_names[index] if index < len(owner_names) else "").strip()
        if not any([trv_id, zone_label, owner_name]):
            continue
        try:
            surface_m2 = float(surface_values[index])
            target_temperature_c = float(target_values[index])
            current_temperature_c = float(current_values[index])
            valve_open_percent = float(valve_values[index])
            duty_value = str(duty_values[index] if index < len(duty_values) else "").strip()
            duty_cycle_percent = float(duty_value) if duty_value else None
        except (TypeError, ValueError):
            return test_consumption_redirect("Valeurs numeriques invalides dans le scenario de consommation")
        samples.append(
            {
                "trv_id": trv_id or f"scenario-{index + 1}",
                "zone_label": zone_label or f"Zone {index + 1}",
                "owner_name": owner_name or f"Occupant {index + 1}",
                "surface_m2": surface_m2,
                "target_temperature_c": target_temperature_c,
                "current_temperature_c": current_temperature_c,
                "valve_open_percent": valve_open_percent,
                "running_state": str(running_states[index] if index < len(running_states) else "unknown").strip(),
                "duty_cycle_percent": duty_cycle_percent,
                "captured_at": "2026-03-11T08:00:00Z",
            }
        )
    if not samples:
        return test_consumption_redirect("Ajoute au moins une ligne de chauffe pour lancer le test de consommation")

    ecs_owner_deltas: dict[str, float] = {}
    for index, owner_name in enumerate(ecs_owner_names):
        normalized_owner_name = str(owner_name).strip()
        if not normalized_owner_name:
            continue
        try:
            ecs_delta = float(ecs_delta_values[index]) if index < len(ecs_delta_values) else 0.0
        except (TypeError, ValueError):
            return test_consumption_redirect("Valeurs ECS invalides dans le scenario de consommation")
        ecs_owner_deltas[normalized_owner_name] = ecs_delta

    try:
        total_bill_amount = float(str(form.get("total_bill_amount", "0")).strip() or "0")
    except ValueError:
        return test_consumption_redirect("Montant total combustible invalide")
    bill_amount_label = str(form.get("bill_amount_label", "EUR")).strip() or "EUR"

    payload = AllocationInput.model_validate({"month_label": month_label, "samples": samples})
    report = build_monthly_allocation(payload)
    ecs_allocation = build_test_ecs_allocation(
        owner_deltas_m3=ecs_owner_deltas,
        total_amount=total_bill_amount,
        amount_label=bill_amount_label,
        period_label=month_label,
    )
    return templates.TemplateResponse(
        request=request,
        name="test_consommation.html",
        context={
            "notice": "Scenario de consommation calcule en mode test. Aucun etat persistant n'a ete modifie.",
            "selected_scenario": scenario,
            "scenario_options": list_test_scenarios(),
            "rows": build_rows(payload),
            "ecs_rows": [
                {"owner_name": owner_name, "ecs_delta_m3": ecs_owner_deltas[owner_name]}
                for owner_name in sorted(ecs_owner_deltas)
            ],
            "month_label": payload.month_label,
            "row_count": len(payload.samples),
            "total_bill_amount": total_bill_amount,
            "bill_amount_label": bill_amount_label,
            "report": report,
            "ecs_allocation": ecs_allocation,
            "combined_rows": build_combined_allocation_rows(report, ecs_allocation=ecs_allocation),
        },
    )


@router.post("/ecs/calculate")
async def ecs_calculate(
    request: Request,
    total_amount: float = Form(...),
    amount_label: str = Form(default="EUR"),
    period_label: str = Form(default=""),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    current_indexes: dict[str, float] = {}
    for key, value in form.multi_items():
        if not key.startswith("ecs_index__"):
            continue
        owner_name = key.removeprefix("ecs_index__").strip()
        if not owner_name:
            continue
        try:
            current_indexes[owner_name] = float(value)
        except (TypeError, ValueError):
            return ecs_redirect(f"Index ECS invalide pour {owner_name}")
    try:
        update_ecs_readings_and_allocate(
            current_indexes_m3=current_indexes,
            total_amount=total_amount,
            amount_label=amount_label,
            period_label=period_label,
        )
    except ValueError as exc:
        return ecs_redirect(str(exc))
    return ecs_redirect("Repartition ECS calculee et index memorises")


@router.post("/admin/archives/rename")
def rename_archive_action(
    request: Request,
    filename: str = Form(...),
    display_name: str = Form(...),
) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    updated = rename_archive(filename=filename, display_name=display_name)
    return admin_redirect(f"Archive renommee: {updated.filename}")


@router.post("/admin/archives/delete")
def delete_archive_action(request: Request, filename: str = Form(...)) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    delete_archive(filename)
    return admin_redirect("Archive supprimee")


@router.get("/admin/archives/export")
def export_archives_action(
    request: Request,
    start_month: str = Query(default=""),
    end_month: str = Query(default=""),
    owner_name: str = Query(default=""),
) -> Response:
    
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    archive_stream, download_name = export_archives_zip(
        start_month=start_month or None,
        end_month=end_month or None,
        owner_name=owner_name or None,
    )
    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(content=archive_stream.getvalue(), media_type="application/zip", headers=headers)


@router.get("/api/report")
def report_json() -> dict:
    report = build_monthly_allocation(load_sample_payload())
    return report.model_dump(mode="json")


@router.get("/reports/monthly.pdf")
def monthly_pdf() -> Response:
    report = build_monthly_allocation(load_sample_payload())
    ecs_allocation = select_ecs_allocation_for_period(load_admin_state(), report.month_label)
    pdf_bytes = build_monthly_pdf(report, ecs_allocation=ecs_allocation)
    headers = {"Content-Disposition": f'inline; filename="thermocalc-{report.month_label}.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/admin/archives/{filename}")
def archived_pdf(request: Request, filename: str) -> Response:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    pdf_path = GENERATED_REPORTS_DIR / sanitize_filename(filename)
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)
