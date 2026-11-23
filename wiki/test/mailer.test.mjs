import assert from "node:assert/strict";
import { test } from "node:test";

import { buildMessage, correctionEmail, requestEmail } from "../mailer/message.js";

const FIXED = { from: "wiki@example.net", to: "me@example.com", siteName: "My Campaign", now: new Date(Date.UTC(2026, 10, 23, 12)), id: "abc" };

test("the request email names the person and gives the approve command", () => {
  const result = requestEmail({ name: "Casey", email: "b@example.com", note: "Nyx's player", siteName: "My Campaign" });

  assert.deepEqual(result, {
    subject: "New wiki access request: Casey (b@example.com)",
    text:
      "Casey (b@example.com) asked to join the My Campaign wiki.\n\nTheir note: Nyx's player\n\nTo let them in:\n" +
      "  cd ~/dev/dnd-transcriber && uv run python wiki/access.py approve b@example.com",
  });
});

test("a name with line breaks cannot add email headers", () => {
  const { subject, text } = requestEmail({ name: "Eve\r\nBcc: victim@example.com", email: "e@example.com", note: "" });

  const raw = buildMessage({ ...FIXED, subject, text });

  assert.equal(raw.split("\r\n\r\n")[0].includes("\r\nBcc:"), false);
});

test("the raw message has the headers Email Routing needs and CRLF line endings", () => {
  const raw = buildMessage({ ...FIXED, subject: "Hi", text: "line one\nline two" });

  assert.equal(
    raw,
    "From: My Campaign wiki <wiki@example.net>\r\nTo: <me@example.com>\r\nSubject: Hi\r\n" +
      "Date: Mon, 23 Nov 2026 12:00:00 GMT\r\nMessage-ID: <abc@example.net>\r\nMIME-Version: 1.0\r\n" +
      "Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\nline one\r\nline two",
  );
});

test("the correction email shows the page link, the correction and the pull command", () => {
  const result = correctionEmail({
    email: "w@example.com", page: "/sessions/session-1/summary/", text: "Sam has the oil.", site: "https://wiki.example",
  });

  assert.deepEqual(result, {
    subject: "Wiki correction from w@example.com: /sessions/session-1/summary/",
    text:
      "w@example.com sent a correction for https://wiki.example/sessions/session-1/summary/\n\nSam has the oil.\n\n" +
      "To pull corrections into the next cleanup:\n" +
      '  cd ~/dev/dnd-transcriber && uv run python wiki/pull_corrections.py "<campaign folder>/corrections.md"',
  });
});
