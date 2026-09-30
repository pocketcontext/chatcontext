import { test, expect } from "@playwright/test";
import { app } from "../src/config";

test("expired persistent tokens and old tab sessions cannot restore login", async ({
  page,
}) => {
  const key = app.name + ".reader.auth";
  await page.addInitScript(
    ({ key, collection }) => {
      const record = { id: "synthetic000001", collectionName: collection };
      const token = (exp: number) =>
        `test.${btoa(JSON.stringify({ exp }))}.test`;
      sessionStorage.setItem(
        key,
        JSON.stringify({ token: token(4102444800), record }),
      );
      localStorage.setItem(key, JSON.stringify({ token: token(1), record }));
    },
    { key, collection: app.authCollection },
  );
  await page.goto("/#/" + app.entities[0].table);
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), key),
  ).toBeNull();
  expect(
    await page.evaluate((key) => localStorage.getItem(key), key),
  ).toBeNull();
});
