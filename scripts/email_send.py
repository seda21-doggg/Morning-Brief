"""Send the daily brief by email via Resend."""
import os

import requests

RESEND_ENDPOINT = "https://api.resend.com/emails"
RECIPIENTS = ["seda.21@seznam.cz", "martin.sedivy@jtfg.com"]


def send_brief_email(date_iso, html_body, sender=None):
    api_key = os.environ["RESEND_API_KEY"]
    sender = sender or os.environ.get("RESEND_FROM") or "Morning Brief <onboarding@resend.dev>"

    resp = requests.post(
        RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": sender,
            "to": RECIPIENTS,
            "subject": f"Morning Brief — {date_iso}",
            "html": html_body,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
