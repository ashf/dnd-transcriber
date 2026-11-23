// Emails the wiki's owner. Called only by the wiki, through a service binding.

import { EmailMessage } from "cloudflare:email";
import { buildMessage, correctionEmail, requestEmail } from "./message.js";

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("POST only", { status: 405 });
    const body = { ...(await request.json()), siteName: env.SITE_NAME };
    const { subject, text } = body.kind === "correction" ? correctionEmail(body) : requestEmail(body);
    const raw = buildMessage({ from: env.NOTIFY_FROM, to: env.NOTIFY_TO, subject, text, siteName: env.SITE_NAME });
    await env.EMAIL.send(new EmailMessage(env.NOTIFY_FROM, env.NOTIFY_TO, raw));
    return new Response("sent");
  },
};
