import assert from "node:assert/strict";
import { test } from "node:test";

import { verifiedEmail } from "../lib/access.js";

const TEAM = "team.cloudflareaccess.com";
const AUD = "aud-custom-domain";
const env = { TEAM_DOMAIN: TEAM, POLICY_AUD: `${AUD},aud-pages-dev` };
const NOW = Date.UTC(2026, 10, 23, 12, 0, 0);
const seconds = NOW / 1000;

const b64url = (bytes) => Buffer.from(bytes).toString("base64url");
const algorithm = { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" };
const signer = await crypto.subtle.generateKey(algorithm, true, ["sign", "verify"]);
const forger = await crypto.subtle.generateKey(algorithm, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", signer.publicKey)), kid: "k1", alg: "RS256" };
const certsFetch = async () => ({ json: async () => ({ keys: [jwk] }) });

async function token(claims, key = signer.privateKey) {
  const head = b64url(JSON.stringify({ alg: "RS256", kid: "k1" }));
  const body = b64url(JSON.stringify(claims));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64url(new Uint8Array(sig))}`;
}

const good = { iss: `https://${TEAM}`, aud: [AUD], email: "Friend@Gmail.com", exp: seconds + 600, nbf: seconds - 60 };
const request = (jwt) => new Request("https://wiki.example/", { headers: jwt ? { "Cf-Access-Jwt-Assertion": jwt } : {} });
const check = async (jwt) => verifiedEmail(request(jwt), env, { fetchImpl: certsFetch, now: NOW });

test("a valid Access token yields the lowercased email", async () => {
  const jwt = await token(good);

  const result = await check(jwt);

  assert.equal(result, "friend@gmail.com");
});

test("a token signed by another key is refused", async () => {
  const jwt = await token(good, forger.privateKey);

  const result = await check(jwt);

  assert.equal(result, null);
});

test("an expired token is refused", async () => {
  const jwt = await token({ ...good, exp: seconds - 1 });

  const result = await check(jwt);

  assert.equal(result, null);
});

test("a token for another Access application is refused", async () => {
  const jwt = await token({ ...good, aud: ["someone-elses-app"] });

  const result = await check(jwt);

  assert.equal(result, null);
});

test("a token from another team is refused", async () => {
  const jwt = await token({ ...good, iss: "https://other.cloudflareaccess.com" });

  const result = await check(jwt);

  assert.equal(result, null);
});

test("a request without a token is refused", async () => {
  const result = await check(null);

  assert.equal(result, null);
});
