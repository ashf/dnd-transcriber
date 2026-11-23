// Stores a request to join the wiki. The middleware has already verified who is asking.

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export async function onRequestPost({ request, env, data, waitUntil }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "expected JSON" }, 400);
  }
  const name = String(body.name || "").trim().slice(0, 100);
  const note = String(body.note || "").trim().slice(0, 1000);
  if (!name) return json({ error: "name required" }, 400);

  await env.DB.prepare(
    "INSERT INTO access_requests (email, name, note, requested_at) VALUES (?1, ?2, ?3, ?4) " +
      "ON CONFLICT(email) DO UPDATE SET name = excluded.name, note = excluded.note, requested_at = excluded.requested_at",
  )
    .bind(data.email, name, note, new Date().toISOString())
    .run();
  if (env.MAILER) {
    // A heads-up for the owner; the request is already saved, so a failed email changes nothing.
    const mail = env.MAILER.fetch("https://wiki-mailer/notify", {
      method: "POST",
      body: JSON.stringify({ name, email: data.email, note }),
    }).catch(() => {});
    waitUntil(mail);
  }
  return json({ ok: true });
}
