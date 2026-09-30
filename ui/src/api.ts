import PocketBase, { BaseAuthStore } from "pocketbase";
import { app, type Entity } from "./config";
const store = new BaseAuthStore();
const key = app.name + ".reader.auth";
try {
  const s = JSON.parse(sessionStorage.getItem(key) || "null");
  if (s?.record?.collectionName === app.authCollection)
    store.save(s.token, s.record);
} catch {
  /* memory session */
}
store.onChange((token, record) => {
  try {
    if (token) sessionStorage.setItem(key, JSON.stringify({ token, record }));
    else sessionStorage.removeItem(key);
  } catch {
    /* memory session */
  }
});
export const pb = new PocketBase(location.origin, store);
pb.autoCancellation(false);
export type Row = Record<string, unknown>;
export const ident = (s: string) => {
  if (!/^[a-z_][a-z0-9_]*$/.test(s)) throw Error("Invalid field");
  return '"' + s + '"';
};
export const literal = (s: string) => "'" + s.replaceAll("'", "''") + "'";
export async function query(sql: string): Promise<Row[]> {
  const token = store.token;
  try {
    const r = await pb.send<{
      columns: string[];
      rows: unknown[][];
      truncated: boolean;
    }>("/api/context/query", { method: "POST", body: { sql } });
    if (token !== store.token) throw Error("Session changed");
    if (r.truncated) throw Error("Response limit reached. Narrow your search.");
    return r.rows.map((row) =>
      Object.fromEntries(r.columns.map((c, i) => [c, row[i]])),
    );
  } catch (e) {
    if ((e as { status?: number }).status === 401 && token === store.token)
      store.clear();
    throw e;
  }
}
export const entity = (table: string) =>
  app.entities.find((e) => e.table === table);
export const label = (e: Entity, r: Row) =>
  e.title
    .map((f) => (f === "id" ? `${e.label} · ${String(r.id).slice(-6)}` : r[f]))
    .filter(Boolean)
    .join(" · ")
    .slice(0, 180) || `${e.label} · ${String(r.id).slice(-6)}`;
export const href = (table: string, id: unknown) =>
  `#/${encodeURIComponent(table)}/${encodeURIComponent(String(id))}`;
export function searchSQL(
  e: Entity,
  q: string,
  filters: Record<string, string>,
  offset = 0,
  relation?: [string, string],
) {
  if (!Number.isSafeInteger(offset) || offset < 0)
    throw Error("Invalid offset");
  const where: string[] = [];
  if (q) {
    const needle = literal(q.toLowerCase());
    where.push(
      "(" +
        ["id", ...e.search]
          .map((f) => `instr(lower(CAST(${ident(f)} AS TEXT)),${needle})>0`)
          .join(" OR ") +
        ")",
    );
  }
  for (const [f, v] of Object.entries(filters))
    if (e.filters?.[f]?.includes(v)) where.push(`${ident(f)}=${literal(v)}`);
  if (relation) where.push(`${ident(relation[0])}=${literal(relation[1])}`);
  return `SELECT * FROM ${ident(e.table)}${where.length ? " WHERE " + where.join(" AND ") : ""} ORDER BY ${q ? `CASE WHEN ${["id", ...e.title].map((f) => `${ident(f)}=${literal(q)}`).join(" OR ")} THEN 0 ELSE 1 END, ` : ""} ${ident(e.title.find((f) => f !== "id") || "id")} COLLATE NOCASE, id LIMIT 31 OFFSET ${offset}`;
}
export function parseRoute() {
  const [path, query = ""] = location.hash.slice(1).split("?");
  const [table, id] = path
    .split("/")
    .filter(Boolean)
    .map((part) => {
      try {
        return decodeURIComponent(part);
      } catch {
        return "";
      }
    });
  return {
    table: entity(table)?.table || app.entities[0].table,
    id: id || "",
    params: safeParams(query),
  };
}

export function safeParams(query: string) {
  const p = new URLSearchParams(query);
  const n = Number(p.get("offset"));
  if (!Number.isSafeInteger(n) || n < 0 || n > 1000000) p.delete("offset");
  return p;
}
