from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from app.models.schemas import EcsAllocationRun, MonthlyAllocationReport
from app.services.archives import upsert_archive_record
from app.services.billing import build_combined_allocation_rows


def build_monthly_pdf(report: MonthlyAllocationReport, ecs_allocation: EcsAllocationRun | None = None) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setTitle(f"ThermoCalc {report.month_label}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(2 * cm, height - 2.5 * cm, f"Rapport mensuel {report.month_label}")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, height - 3.3 * cm, f"Methode: {report.methodology}")
    pdf.drawString(2 * cm, height - 3.9 * cm, "Repartition relative basee sur delta, surface et facteur de demande compose.")
    if ecs_allocation is not None:
        ecs_period = ecs_allocation.period_label or report.month_label
        pdf.drawString(
            2 * cm,
            height - 4.5 * cm,
            f"Facture combustible: {ecs_allocation.total_amount:.2f} {ecs_allocation.amount_label} repartie pour {ecs_period}.",
        )

    y = height - 5.2 * cm
    pdf.setFillColor(colors.HexColor("#17324d"))
    pdf.rect(2 * cm, y, width - 4 * cm, 0.7 * cm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 11)
    combined_rows = build_combined_allocation_rows(report, ecs_allocation=ecs_allocation)
    pdf.drawString(2.2 * cm, y + 0.23 * cm, "Occupant")
    pdf.drawString(6.7 * cm, y + 0.23 * cm, "Chauff.")
    pdf.drawString(9.2 * cm, y + 0.23 * cm, "ECS")
    pdf.drawString(11.6 * cm, y + 0.23 * cm, "Part finale")
    pdf.drawString(14.5 * cm, y + 0.23 * cm, "Montant")
    pdf.drawString(17.0 * cm, y + 0.23 * cm, "Surf.")

    y -= 0.7 * cm
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 10)
    for row in combined_rows:
        pdf.drawString(2.2 * cm, y + 0.2 * cm, str(row["owner_name"]))
        pdf.drawRightString(8.8 * cm, y + 0.2 * cm, f"{float(row['heating_share_percent']):.2f} %")
        pdf.drawRightString(11.2 * cm, y + 0.2 * cm, f"{float(row['ecs_share_percent']):.2f} %")
        pdf.drawRightString(14.2 * cm, y + 0.2 * cm, f"{float(row['combined_share_percent']):.2f} %")
        pdf.drawRightString(16.8 * cm, y + 0.2 * cm, f"{float(row['combined_allocated_amount']):.2f}")
        pdf.drawRightString(17.6 * cm, y + 0.2 * cm, f"{float(row['tracked_surface_m2']):.1f} m2")
        y -= 0.65 * cm

    y -= 0.4 * cm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(2 * cm, y, "Detail par tete thermostatique")
    y -= 0.6 * cm
    pdf.setFont("Helvetica", 9)
    for zone in report.zones:
        line = (
            f"{zone.owner_name} | {zone.zone_label} | delta {zone.delta_c:.1f} C | "
            f"surface {zone.surface_m2:.1f} m2 | vanne {zone.valve_factor * 100:.0f}% | "
            f"etat {zone.running_state} | duty {(zone.duty_cycle_percent if zone.duty_cycle_percent is not None else 0):.1f}% | "
            f"demande {zone.demand_factor * 100:.0f}% | score {zone.effort_score:.2f}"
        )
        pdf.drawString(2 * cm, y, line)
        y -= 0.45 * cm
        if y < 2.5 * cm:
            y = _new_page(pdf, height)

    pdf.save()
    return buffer.getvalue()
def _new_page(pdf: canvas.Canvas, height: float) -> float:
    pdf.showPage()
    pdf.setFont("Helvetica", 9)
    return height - 2.5 * cm


def save_monthly_pdf(
    report: MonthlyAllocationReport,
    output_path: Path,
    ecs_allocation: EcsAllocationRun | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_monthly_pdf(report, ecs_allocation=ecs_allocation))
    upsert_archive_record(report, output_path)
    return output_path
