import asyncio
from datetime import datetime
from pathlib import Path

from app.core.config import GENERATED_REPORTS_DIR, SCHEDULER_POLL_SECONDS
from app.models.schemas import MonthlyAllocationReport, PdfScheduleConfig
from app.services.admin_state import load_admin_state, mark_report_generated
from app.services.reporting import save_monthly_pdf
from app.services.runtime_measurements import sync_runtime_subscriptions
from app.services.zigbee2mqtt import refresh_due_controllers



def should_generate_report(now: datetime, schedule: PdfScheduleConfig, month_label: str) -> bool:
    if not schedule.enabled:
        return False
    if schedule.last_generated_month == month_label:
        return False
    if now.day != schedule.day_of_month:
        return False
    if now.hour < schedule.hour:
        return False
    if now.hour == schedule.hour and now.minute < schedule.minute:
        return False
    return True



def run_scheduled_generation_once(report: MonthlyAllocationReport, force: bool = False, output_path: Path | None = None) -> Path:
    state = load_admin_state()
    destination = output_path or GENERATED_REPORTS_DIR / f"thermocalc-{report.month_label}.pdf"
    if not force:
        now = datetime.now()
        if not should_generate_report(now, state.schedule, report.month_label):
            raise RuntimeError("Report generation is not due yet")
    output_file = save_monthly_pdf(report, destination)
    mark_report_generated(report.month_label)
    return output_file


async def scheduler_loop() -> None:
    from app.api.routes import load_sample_payload
    from app.services.consumption import build_monthly_allocation

    while True:
        try:
            state = load_admin_state()
            sync_runtime_subscriptions(state)
            refresh_due_controllers()
            payload = load_sample_payload()
            report = build_monthly_allocation(payload)
            if should_generate_report(datetime.now(), state.schedule, report.month_label):
                run_scheduled_generation_once(
                    report=report,
                    output_path=GENERATED_REPORTS_DIR / f"thermocalc-{report.month_label}.pdf",
                )
        except Exception:
            pass
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)
