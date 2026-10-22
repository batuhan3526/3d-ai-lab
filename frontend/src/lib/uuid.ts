// RFC4122 v4 UUID with a safe fallback for non-secure contexts.
//
// `crypto.randomUUID()` only exists in a *secure context* (https:// or
// localhost). When the app is served over plain HTTP on the LAN (the common
// "share with the room" case), `crypto.randomUUID` is `undefined`, so calling
// it throws — which used to blow up "add decal" / "duplicate decal". This
// helper prefers the native call and otherwise builds a v4 UUID from
// `crypto.getRandomValues` (available over HTTP), degrading to `Math.random`
// only if no Web Crypto is present at all.
export function uuid(): string {
  const c: Crypto | undefined = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === "function") {
    c.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  // Set version (4) and variant (10xx) bits per RFC 4122 §4.4.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex: string[] = [];
  for (let i = 0; i < 256; i++) hex.push((i + 0x100).toString(16).slice(1));
  return (
    hex[bytes[0]] + hex[bytes[1]] + hex[bytes[2]] + hex[bytes[3]] + "-" +
    hex[bytes[4]] + hex[bytes[5]] + "-" +
    hex[bytes[6]] + hex[bytes[7]] + "-" +
    hex[bytes[8]] + hex[bytes[9]] + "-" +
    hex[bytes[10]] + hex[bytes[11]] + hex[bytes[12]] +
    hex[bytes[13]] + hex[bytes[14]] + hex[bytes[15]]
  );
}
