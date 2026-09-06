"""Send the daily brief by email via Gmail SMTP (app password auth)."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
RECIPIENTS = ["seda.21@seznam.cz", "martin.sedivy@jtfg.com"]


def send_brief_email(date_iso, html_body):
    address = os.environ["GMAIL_ADDRESS"]
    # Google displays the app password with spaces for readability; strip them
    # in case it was pasted verbatim into the secret.
    app_password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Morning Brief — {date_iso}"
    msg["From"] = address
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(address, app_password)
        server.sendmail(address, RECIPIENTS, msg.as_string())
