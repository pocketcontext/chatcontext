import { describe, it, expect, vi } from "vitest";
import { app } from "./config";
import {
  pb,
  query,
  searchSQL,
  ident,
  literal,
  parseRoute,
  safeParams,
} from "./api";
import schema from "../../pocketcontext.json";
describe("reader contract", () => {
  it("only references exported fields and configured relationship targets", () => {
    const tables = schema.tables as Record<string, string[]>;
    for (const e of app.entities) {
      expect(tables[e.table]).toBeDefined();
      for (const field of [
        ...e.title,
        ...e.search,
        ...(e.subtitle || []),
        ...Object.keys(e.filters || {}),
        ...Object.keys(e.relations || {}),
        ...(e.markdown || []),
        ...(e.hidden || []),
      ])
        expect(tables[e.table], e.table + "." + field).toContain(field);
      for (const target of Object.values(e.relations || {}))
        expect(
          app.entities.some((e) => e.table === target),
          target,
        ).toBe(true);
    }
    expect(
      app.entities.some((e) =>
        [
          "users",
          "agents",
          "finance_members",
          "team_members",
          "hr_members",
          "account_links",
          "reporting_lines",
        ].includes(e.table),
      ),
    ).toBe(false);
  });
  it("quotes malicious search literals and bounds pagination", () => {
    const sql = searchSQL(app.entities[0], "x' OR 1=1 --", {}, 30);
    expect(sql).toContain("'x'' or 1=1 --'");
    expect(sql).toContain("LIMIT 31 OFFSET 30");
    expect(() => ident("users;DELETE")).toThrow();
    expect(() => searchSQL(app.entities[0], "", {}, -1)).toThrow();
    expect(literal("O'Neil")).toBe("'O''Neil'");
  });
  it("handles damaged links and unsafe offsets without crashing", () => {
    location.hash = "#/employees/%E0%A4%A?offset=Infinity";
    expect(() => parseRoute()).not.toThrow();
    expect(safeParams("offset=Infinity").has("offset")).toBe(false);
    expect(safeParams("offset=-3").has("offset")).toBe(false);
    expect(safeParams("offset=30").get("offset")).toBe("30");
  });
});

it("clears the session on an authenticated SQL denial", async () => {
  pb.authStore.save("test-session", null);
  const send = vi.spyOn(pb, "send").mockRejectedValueOnce({ status: 403 });
  await expect(
    query("SELECT id FROM " + app.entities[0].table),
  ).rejects.toEqual({ status: 403 });
  expect(pb.authStore.token).toBe("");
  send.mockRestore();
});
