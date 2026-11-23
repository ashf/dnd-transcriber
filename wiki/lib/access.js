// Verifies the Cloudflare Access login token on a request and returns the signed-in email, or null.
// Access proves who someone is; the wiki's members list decides whether they get in, so the token's
// signature, issuer, audience and lifetime are all checked rather than trusting any header.

const keyCache = new Map();

function base64UrlBytes(text) {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function decodePart(text) {
  return JSON.parse(new TextDecoder().decode(base64UrlBytes(text)));
}

async function signingKey(teamDomain, kid, fetchImpl) {
  const cacheKey = `${teamDomain}/${kid}`;
  if (!keyCache.has(cacheKey)) {
    const response = await fetchImpl(`https://${teamDomain}/cdn-cgi/access/certs`);
    const { keys = [] } = await response.json();
    for (const jwk of keys) {
      const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
      keyCache.set(`${teamDomain}/${jwk.kid}`, key);
    }
  }
  return keyCache.get(cacheKey) || null;
}

export async function verifiedEmail(request, env, { fetchImpl = fetch, now = Date.now() } = {}) {
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token || !env.TEAM_DOMAIN || !env.POLICY_AUD) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const header = decodePart(parts[0]);
    const claims = decodePart(parts[1]);
    if (header.alg !== "RS256") return null;
    const key = await signingKey(env.TEAM_DOMAIN, header.kid, fetchImpl);
    if (!key) return null;
    const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
    if (!(await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, base64UrlBytes(parts[2]), signed))) return null;
    const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    const allowed = env.POLICY_AUD.split(",").map((a) => a.trim());
    const seconds = now / 1000;
    if (claims.iss !== `https://${env.TEAM_DOMAIN}`) return null;
    if (!audiences.some((a) => allowed.includes(a))) return null;
    if (!(claims.exp > seconds) || (claims.nbf && claims.nbf > seconds)) return null;
    return typeof claims.email === "string" ? claims.email.toLowerCase() : null;
  } catch {
    return null;
  }
}
