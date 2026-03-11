from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from app.models.schemas import MonthlyAllocationReport
from app.services.archives import upsert_archive_record



def build_monthly_pdf(report: MonthlyAllocationReport) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setTitle(f"ThermoCalc {report.month_label}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(2 * cm, height - 2.5 * cm, f"Rapport mensuel {report.month_label}")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, height - 3.3 * cm, f"Methode: {report.methodology}")
    pdf.drawString(2 * cm, height - 3.9 * cm, "Repartition relative basee sur consigne, temperature reelle, surface et ouverture de vanne.")

    y = height - 5.2 * cm
    pdf.setFillColor(colors.HexColor("#17324d"))
    pdf.rect(2 * cm, y, width - 4 * cm, 0.7 * cm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(2.2 * cm, y + 0.23 * cm, "Occupant")
    pdf.drawString(8.4 * cm, y + 0.23 * cm, "Part")
    pdf.drawString(11.4 * cm, y + 0.23 * cm, "Score")
    pdf.drawString(14.6 * cm, y + 0.23 * cm, "Surface")

    y -= 0.7 * cm
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 10)
    for allocation in report.allocations:
        pdf.drawString(2.2 * cm, y + 0.2 * cm, allocation.owner_name)
        pdf.drawRightString(10.4 * cm, y + 0.2 * cm, f"{allocation.share_percent:.2f} %")
        pdf.drawRightString(13.6 * cm, y + 0.2 * cm, f"{allocation.total_effort_score:.2f}")
        pdf.drawRightString(17.6 * cm, y + 0.2 * cm, f"{allocation.tracked_surface_m2:.1f} m2")
        y -= 0.65 * cm

    y -= 0.4 * cm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(2 * cm, y, "Detail par tete thermostatique")
    y -= 0.6 * cm
    pdf.setFont("Helvetica", 9)
    for zone in report.zones:
        line = (
            f"{zone.owner_name} | {zone.zone_label} | delta {zone.delta_c:.1f} C | "
            f"surface {zone.surface_m2:.1f} m2 | vanne {zone.valve_factor * 100:.0f}% | score {zone.effort_score:.2f}"
        )
        pdf.drawString(2 * cm, y, line)
        y -= 0.45 * cm
        if y < 2.5 * cm:
            pdf.showPage()
            y = height - 2.5 * cm
            pdf.setFont("Helvetica", 9)

    pdf.save()
    return buffer.getvalue()


def save_monthly_pdf(report: MonthlyAllocationReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_monthly_pdf(report))
    upsert_archive_record(report, output_path)
    return output_path
