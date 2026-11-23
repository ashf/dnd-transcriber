// Runs in front of every page and file. Only members see the wiki; anyone else who signed in through
// Cloudflare Access gets the request-access page instead.

import { verifiedEmail } from "../lib/access.js";

const html = (body, status = 200) =>
  new Response(body, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });

const escape = (text) => text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function requestPage(email, pending) {
  const body = pending
    ? `<p>Your request is in. You will be able to read the wiki once it is approved.</p>`
    : `<form id="request">
        <label>Your name<input name="name" maxlength="100" required></label>
        <label>Anything we should know? (optional)<textarea name="note" rows="3" maxlength="1000"></textarea></label>
        <button type="submit">Request access</button>
        <p id="status" role="status"></p>
      </form>
      <script>
        document.getElementById("request").addEventListener("submit", async (event) => {
          event.preventDefault();
          const form = new FormData(event.target);
          const status = document.getElementById("status");
          status.textContent = "Sending...";
          const response = await fetch("/api/request-access", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: form.get("name"), note: form.get("note") }),
          });
          status.textContent = response.ok ? "Request sent. You will get in once it is approved." : "Could not send it (" + response.status + ").";
        });
      </script>`;
  return html(`<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Request access</title>
    <style>
      body{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#e8e6f0;background:#1e1b2e}
      label{display:block;margin:1rem 0}input,textarea{display:block;width:100%;margin-top:.3rem;padding:.5rem;font:inherit;
      color:inherit;background:#2b2740;border:1px solid #5a5478;border-radius:4px}button{padding:.6rem 1.2rem;font:inherit;
      color:#fff;background:#7e57c2;border:0;border-radius:4px;cursor:pointer}
    </style></head><body><h1>This wiki is private</h1>
    <p>You are signed in as <strong>${escape(email)}</strong>, which is not on the members list yet.</p>${body}</body></html>`, 403);
}

export async function onRequest(context) {
  const { request, env, next, data } = context;
  const email = await verifiedEmail(request, env);
  if (!email) return new Response("Sign in through the wiki's address to continue.", { status: 401 });
  data.email = email;

  const member = await env.DB.prepare("SELECT 1 FROM members WHERE email = ?1").bind(email).first();
  if (member) return next();
  if (new URL(request.url).pathname === "/api/request-access") return next();

  const pending = await env.DB.prepare("SELECT 1 FROM access_requests WHERE email = ?1").bind(email).first();
  return requestPage(email, Boolean(pending));
}
