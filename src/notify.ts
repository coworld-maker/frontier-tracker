import nodemailer from "nodemailer";
import https from "https";
import type { GoWildFlight, NotifyConfig } from "./types.js";

function formatFlightList(flights: GoWildFlight[]): string {
  return flights
    .map((f) => {
      const price = f.price === 0 ? "FREE (taxes only)" : `$${f.price} ${f.currency}`;
      return `• ${f.origin} → ${f.destination}  |  ${f.date} ${f.departureTime}  |  Flight ${f.flightNumber}  |  ${price}`;
    })
    .join("\n");
}

function formatHtml(flights: GoWildFlight[]): string {
  const rows = flights
    .map((f) => {
      const price = f.price === 0 ? "FREE (taxes only)" : `$${f.price} ${f.currency}`;
      return `<tr>
        <td>${f.origin} → ${f.destination}</td>
        <td>${f.date}</td>
        <td>${f.departureTime}</td>
        <td>${f.flightNumber}</td>
        <td><strong>${price}</strong></td>
      </tr>`;
    })
    .join("");

  return `<html><body>
    <h2>✈ Frontier Go Wild Seats Available!</h2>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:monospace">
      <thead>
        <tr><th>Route</th><th>Date</th><th>Departs</th><th>Flight</th><th>Price</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <p style="color:#888;font-size:12px">Book at <a href="https://www.flyfrontier.com">flyfrontier.com</a></p>
  </body></html>`;
}

export async function sendNotifications(
  flights: GoWildFlight[],
  config: NotifyConfig
): Promise<void> {
  if (flights.length === 0) return;

  const subject = `Go Wild Alert: ${flights.length} seat${flights.length > 1 ? "s" : ""} available`;
  const text = `Frontier Go Wild seats found!\n\n${formatFlightList(flights)}\n\nBook at https://www.flyfrontier.com`;

  const tasks: Promise<void>[] = [];

  if (config.email?.enabled) tasks.push(sendEmail(subject, text, formatHtml(flights), config.email));
  if (config.pushover?.enabled) tasks.push(sendPushover(subject, text, config.pushover));
  if (config.slack?.enabled) tasks.push(sendSlack(subject, flights, config.slack));
  if (config.discord?.enabled) tasks.push(sendDiscord(subject, flights, config.discord));

  await Promise.allSettled(tasks).then((results) => {
    results.forEach((r) => {
      if (r.status === "rejected") console.error("Notification error:", r.reason);
    });
  });
}

async function sendEmail(
  subject: string,
  text: string,
  html: string,
  cfg: NonNullable<NotifyConfig["email"]>
): Promise<void> {
  const transporter = nodemailer.createTransport({
    host: cfg.smtp.host,
    port: cfg.smtp.port,
    secure: cfg.smtp.secure ?? cfg.smtp.port === 465,
    auth: { user: cfg.smtp.user, pass: cfg.smtp.pass },
  });

  await transporter.sendMail({
    from: `"Go Wild Tracker" <${cfg.smtp.user}>`,
    to: cfg.to,
    subject,
    text,
    html,
  });
  console.log("  Email sent.");
}

async function sendPushover(
  title: string,
  message: string,
  cfg: NonNullable<NotifyConfig["pushover"]>
): Promise<void> {
  const payload = JSON.stringify({
    token: cfg.apiToken,
    user: cfg.userKey,
    title,
    message,
    url: "https://www.flyfrontier.com",
    url_title: "Book on Frontier",
    priority: 0,
  });

  await post("api.pushover.net", "/1/messages.json", payload);
  console.log("  Pushover sent.");
}

async function sendSlack(
  title: string,
  flights: GoWildFlight[],
  cfg: NonNullable<NotifyConfig["slack"]>
): Promise<void> {
  const blocks = [
    { type: "header", text: { type: "plain_text", text: `✈ ${title}` } },
    {
      type: "section",
      text: {
        type: "mrkdwn",
        text: formatFlightList(flights),
      },
    },
    {
      type: "actions",
      elements: [
        {
          type: "button",
          text: { type: "plain_text", text: "Book on Frontier" },
          url: "https://www.flyfrontier.com",
          style: "primary",
        },
      ],
    },
  ];

  const url = new URL(cfg.webhookUrl);
  await post(url.hostname, url.pathname, JSON.stringify({ blocks }));
  console.log("  Slack sent.");
}

async function sendDiscord(
  title: string,
  flights: GoWildFlight[],
  cfg: NonNullable<NotifyConfig["discord"]>
): Promise<void> {
  const embeds = [
    {
      title: `✈ ${title}`,
      color: 0x00a651, // Frontier green
      description: formatFlightList(flights),
      url: "https://www.flyfrontier.com",
      footer: { text: "Book at flyfrontier.com" },
      timestamp: new Date().toISOString(),
    },
  ];

  const url = new URL(cfg.webhookUrl);
  await post(url.hostname, url.pathname + url.search, JSON.stringify({ embeds }));
  console.log("  Discord sent.");
}

function post(hostname: string, path: string, body: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname,
        path,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
      },
      (res) => {
        res.resume();
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode} from ${hostname}${path}`));
        } else {
          resolve();
        }
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}
