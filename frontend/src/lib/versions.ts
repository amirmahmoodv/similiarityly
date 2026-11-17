/** Qdrant supports a client at most one minor version away from the server. */
export function versionsTooFarApart(server?: string | null, client?: string | null): boolean {
  const s = majorMinor(server);
  const c = majorMinor(client);
  if (!s || !c) return false;
  return s[0] !== c[0] || Math.abs(s[1] - c[1]) > 1;
}

function majorMinor(version?: string | null): [number, number] | null {
  const m = version?.match(/^v?(\d+)\.(\d+)/);
  return m ? [Number(m[1]), Number(m[2])] : null;
}
