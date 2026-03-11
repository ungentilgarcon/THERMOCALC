import json
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import (
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
    add_or_update_controller,
    add_or_update_thermostat,
    add_or_update_zigbee_device,
    add_or_update_zigbee_pairing,
    add_occupant,
    apply_assignments_to_payload,
    load_admin_state,
    remove_controller,
    remove_occupant,
    remove_thermostat,
    remove_zigbee_device,
    remove_zigbee_pairing,
    update_schedule,
)
from app.services.auth import ensure_admin, is_admin_authenticated, login_admin, logout_admin
from app.services.consumption import build_monthly_allocation
from app.services.reporting import build_monthly_pdf
from app.services.runtime_measurements import build_realtime_payload
from app.services.scheduler import run_scheduled_generation_once
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


def load_sample_payload() -> AllocationInput:
    admin_state = load_admin_state()
    realtime_payload = build_realtime_payload(admin_state)
    if realtime_payload is not None:
        return realtime_payload
    content = json.loads(Path(SAMPLE_DATA_PATH).read_text(encoding="utf-8"))
    payload = AllocationInput.model_validate(content)
    return apply_assignments_to_payload(payload, admin_state)


def admin_redirect(notice: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin?notice={quote_plus(notice)}", status_code=303)


def admin_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=303)


def sanitize_filename(filename: str) -> str:
    return Path(filename).name


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    report = build_monthly_allocation(load_sample_payload())
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"report": report},
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
    report = build_monthly_allocation(load_sample_payload())
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
            },
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


@router.post("/admin/reports/generate")
def generate_pdf_now(request: Request) -> RedirectResponse:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    report = build_monthly_allocation(load_sample_payload())
    output_path = GENERATED_REPORTS_DIR / f"thermocalc-{report.month_label}.pdf"
    output_file = run_scheduled_generation_once(report=report, force=True, output_path=output_path)
    return admin_redirect(f"PDF genere: {output_file.name}")


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
    pdf_bytes = build_monthly_pdf(report)
    headers = {"Content-Disposition": f'inline; filename="thermocalc-{report.month_label}.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/admin/archives/{filename}")
def archived_pdf(request: Request, filename: str) -> Response:
    redirect = ensure_admin(request)
    if redirect:
        return redirect
    pdf_path = GENERATED_REPORTS_DIR / sanitize_filename(filename)
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)
