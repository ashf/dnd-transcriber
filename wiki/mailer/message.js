// Builds a plain-text email in the raw MIME form Cloudflare's send_email binding takes.

const oneLine = (text) => String(text).replace(/[\r\n]+/g, " ").trim();

export function buildMessage({ from, to, subject, text, siteName, now = new Date(), id = crypto.randomUUID() }) {
  const domain = from.split("@")[1];
  return [
    `From: ${oneLine(siteName)} wiki <${from}>`,
    `To: <${to}>`,
    `Subject: ${oneLine(subject)}`,
    `Date: ${now.toUTCString()}`,
    `Message-ID: <${id}@${domain}>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: 8bit",
    "",
    String(text).replace(/\r?\n/g, "\r\n"),
  ].join("\r\n");
}

export function requestEmail({ name, email, note, siteName }) {
  return {
    subject: `New wiki access request: ${oneLine(name)} (${oneLine(email)})`,
    text: [
      `${oneLine(name)} (${oneLine(email)}) asked to join the ${oneLine(siteName)} wiki.`,
      note ? `\nTheir note: ${note}` : "",
      "\nTo let them in:",
      `  cd ~/dev/dnd-transcriber && uv run python wiki/access.py approve ${oneLine(email)}`,
    ].join("\n"),
  };
}

export function correctionEmail({ email, page, text, site }) {
  return {
    subject: `Wiki correction from ${oneLine(email)}: ${oneLine(page)}`,
    text: [
      `${oneLine(email)} sent a correction for ${site}${oneLine(page)}`,
      `\n${text}`,
      "\nTo pull corrections into the next cleanup:",
      '  cd ~/dev/dnd-transcriber && uv run python wiki/pull_corrections.py "<campaign folder>/corrections.md"',
    ].join("\n"),
  };
}
