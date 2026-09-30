import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const f = JSON.parse(readFileSync(process.env.READER_TEST_FIXTURE!, "utf8"));
test("record discovery, direct links, relationships and revoked access", async ({
  page,
  request,
  context,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/#/" + f.table + "/" + f.id);
  await page.getByLabel("Email", { exact: true }).fill(f.email);
  await page.getByLabel("Password", { exact: true }).fill(f.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: f.title, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: f.relationTitle, exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Copy record link", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toContain("/#/" + f.table + "/" + f.id);
  await page.screenshot({
    path: process.env.READER_SCREENSHOT_DIR + "/chatcontext-desktop.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: f.title, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/offset=30/);
  await expect(page.locator(".result")).toHaveCount(5);
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("searchbox").fill(f.needle);
  await expect(page.locator(".result")).toHaveCount(1);
  await expect(page.locator(".result")).toContainText(f.needle);
  await page
    .getByRole("button", { name: "Copy search link", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toContain("q=");
  await page.locator(".result").click();
  await expect(
    page.getByRole("heading", { name: f.needle, exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: f.title, exact: true }),
  ).toBeVisible();
  await page.goto("/#/" + f.forbiddenTable + "/" + f.forbiddenId);
  await expect(page.getByRole("alert")).toContainText("unavailable");
  await expect(page.locator(".detail")).not.toContainText(f.forbiddenText);
  if (f.allocationId) {
    await page.goto("/#/claim_reimbursements/" + f.allocationId);
    await expect(
      page.getByText("Unavailable", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.locator(".detail")).not.toContainText(f.forbiddenId);
  }
  if (f.fileId) {
    await page.goto("/#/" + f.fileTable + "/" + f.fileId);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download original" }).click();
    const saved = await download;
    expect(saved.suggestedFilename()).toMatch(/\.txt$/);
    expect(readFileSync((await saved.path())!, "utf8")).toContain("Synthetic");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/" + f.table + "/" + f.id);
  await expect(
    page.getByRole("heading", { name: f.title, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await expect(page.getByRole("combobox").first()).toBeVisible();
  await page.getByRole("searchbox").fill(f.needle);
  await expect(page.locator(".result")).toHaveCount(1);
  await page.locator(".result").click();
  await expect(
    page.getByRole("heading", { name: f.needle, exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: process.env.READER_SCREENSHOT_DIR + "/chatcontext-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await request.post(process.env.READER_TEST_CONTROL + "/assert-unread");
  await request.post(process.env.READER_TEST_CONTROL + "/revoke");
  await page.goto(
    "/#/" +
      (f.table === "employees" ? "hr_notes" : f.table) +
      "/" +
      (f.table === "employees" ? f.revokeId : f.id),
  );
  await page.reload();
  if (f.table === "employees") {
    await expect(page.getByRole("alert")).toContainText("unavailable");
    await expect(page.locator(".detail")).not.toContainText(f.forbiddenText);
  } else
    await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
