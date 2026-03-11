import smtplib
from email.message import EmailMessage

from app.core.config import ALERT_EMAIL_FROM, ALERT_EMAIL_TO, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME, SMTP_USE_TLS


def send_low_battery_alert(device_id: str, battery_percent: int, owner_name: str = "", zone_label: str = "") -> bool:
    if not SMTP_HOST or not ALERT_EMAIL_TO:
        return False

    message = EmailMessage()
    message["Subject"] = f"Alerte ThermoCalc: pile faible sur {device_id}"
    message["From"] = ALERT_EMAIL_FROM
    message["To"] = ALERT_EMAIL_TO
    location = ""
    if owner_name or zone_label:
        location = f"Occupant: {owner_name or 'non renseigne'}\nZone: {zone_label or 'non renseignee'}\n"
    message.set_content(
        "Une tete thermostatique TRV26 est passee sous le seuil de batterie.\n\n"
        f"Device: {device_id}\n"
        f"Batterie: {battery_percent}%\n"
        f"{location}"
        "Action recommandee: remplacer les piles.\n"
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)
    return True