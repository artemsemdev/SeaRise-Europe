import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const forbiddenPaths = ["ass" + "ess", "geo" + "code", "con" + "fig"];

test("landing shell is static, keyboard reachable, and has no serious accessibility findings", async ({ page }) => {
  const forbiddenRequests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname.toLowerCase();
    if (forbiddenPaths.some((part) => path.includes(part))) forbiddenRequests.push(path);
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Take me there");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await expect(page.getByText(/Synthetic fixture · illustrative only/i)).toBeVisible();
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();

  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
  expect(forbiddenRequests).toEqual([]);
});

test("manifest delivery failure has bounded same-release retry", async ({ page }) => {
  const manifestPaths = new Set<string>();
  await page.route("**/releases/**/manifest.json", async (route) => {
    manifestPaths.add(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /retry pinned release/i }).click();
  await page.getByRole("button", { name: /retry pinned release/i }).click();

  await expect(page.getByText(/retry limit reached/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /retry pinned release/i })).toHaveCount(0);
  expect([...manifestPaths]).toEqual([
    "/releases/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json",
  ]);
});

test("architecture direct navigation works from static output", async ({ page }) => {
  await page.goto("/about/architecture/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Static-first");
  await expect(page.getByText(/synthetic fixture/i).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /back to explorer/i })).toHaveAttribute("href", "/");
});
