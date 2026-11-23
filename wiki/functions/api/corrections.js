// Stores a correction from the wiki's form. The middleware has already checked that the sender is a member.

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export async function onRequestPost({ request, env, data, waitUntil }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "expected JSON" }, 400);
  }
  const page = String(body.page || "").slice(0, 300);
  const text = String(body.text || "").trim().slice(0, 5000);
  if (!text) return json({ error: "empty correction" }, 400);

  await env.DB.prepare("INSERT INTO corrections (page, text, email, created_at) VALUES (?1, ?2, ?3, ?4)")
    .bind(page, text, data.email, new Date().toISOString())
    .run();
  if (env.MAILER) {
    // A heads-up for the owner; the correction is already saved, so a failed email changes nothing.
    const site = new URL(request.url).origin;
    const mail = env.MAILER.fetch("https://wiki-mailer/notify", {
      method: "POST",
      body: JSON.stringify({ kind: "correction", email: data.email, page, text, site }),
    }).catch(() => {});
    waitUntil(mail);
  }
  return json({ ok: true });
}
