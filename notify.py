import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from scraper import GoWildFlight


def _flight_list_text(flights: list[GoWildFlight]) -> str:
    return "\n".join(f"• {f.label()}" for f in flights)


def _flight_list_html(flights: list[GoWildFlight]) -> str:
    rows = "".join(
        f"<tr>"
        f"<td>{f.origin} → {f.destination}</td>"
        f"<td>{f.date}</td>"
        f"<td>{f.departure_time}</td>"
        f"<td>{f.flight_number}</td>"
        f"<td><strong>{'FREE (taxes only)' if f.price == 0 else f'${f.price:.0f} {f.currency}'}</strong></td>"
        f"</tr>"
        for f in flights
    )
    return f"""<html><body>
<h2>✈ Frontier Go Wild Seats Available!</h2>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:monospace">
  <thead>
    <tr><th>Route</th><th>Date</th><th>Departs</th><th>Flight</th><th>Price</th></tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<p style="color:#888;font-size:12px">Book at <a href="https://www.flyfrontier.com">flyfrontier.com</a></p>
</body></html>"""


def _send_email(subject: str, body_text: str, body_html: str, cfg: dict) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Go Wild Tracker <{cfg['smtp']['user']}>"
    msg["To"] = cfg["to"]
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    smtp_cfg = cfg["smtp"]
    port = smtp_cfg.get("port", 587)
    secure = smtp_cfg.get("secure", port == 465)

    if secure:
        with smtplib.SMTP_SSL(smtp_cfg["host"], port) as server:
            server.login(smtp_cfg["user"], smtp_cfg["pass"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_cfg["host"], port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_cfg["user"], smtp_cfg["pass"])
            server.send_message(msg)
    print("  Email sent.")


def _send_pushover(title: str, message: str, cfg: dict) -> None:
    resp = requests.post(
        "https://api.pushover.net/1/messages.json",
        json={
            "token": cfg["apiToken"],
            "user": cfg["userKey"],
            "title": title,
            "message": message,
            "url": "https://www.flyfrontier.com",
            "url_title": "Book on Frontier",
            "priority": 0,
        },
        timeout=10,
    )
    resp.raise_for_status()
    print("  Pushover sent.")


def _send_slack(title: str, flights: list[GoWildFlight], cfg: dict) -> None:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"✈ {title}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _flight_list_text(flights)}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Book on Frontier"},
                    "url": "https://www.flyfrontier.com",
                    "style": "primary",
                }
            ],
        },
    ]
    resp = requests.post(cfg["webhookUrl"], json={"blocks": blocks}, timeout=10)
    resp.raise_for_status()
    print("  Slack sent.")


def _send_discord(title: str, flights: list[GoWildFlight], cfg: dict) -> None:
    embeds = [
        {
            "title": f"✈ {title}",
            "color": 0x00A651,
            "description": _flight_list_text(flights),
            "url": "https://www.flyfrontier.com",
            "footer": {"text": "Book at flyfrontier.com"},
        }
    ]
    resp = requests.post(cfg["webhookUrl"], json={"embeds": embeds}, timeout=10)
    resp.raise_for_status()
    print("  Discord sent.")


def send_notifications(flights: list[GoWildFlight], config: dict) -> None:
    if not flights:
        return

    n = len(flights)
    subject = f"Go Wild Alert: {n} seat{'s' if n != 1 else ''} available"
    body_text = f"Frontier Go Wild seats found!\n\n{_flight_list_text(flights)}\n\nBook at https://www.flyfrontier.com"

    notifications = config.get("notifications", {})

    channels = [
        ("email",   lambda: _send_email(subject, body_text, _flight_list_html(flights), notifications["email"])),
        ("pushover", lambda: _send_pushover(subject, body_text, notifications["pushover"])),
        ("slack",   lambda: _send_slack(subject, flights, notifications["slack"])),
        ("discord", lambda: _send_discord(subject, flights, notifications["discord"])),
    ]

    for key, fn in channels:
        cfg = notifications.get(key, {})
        if cfg.get("enabled"):
            try:
                fn()
            except Exception as e:
                print(f"  {key} notification error: {e}")
