import { test, expect } from "@playwright/test";

// Tam yığın gerektirir: Redis + gateway + Celery worker + frontend.
// M1'de worker placeholder olduğundan GPU gerekmez. E2E_FULL_STACK set değilse skip.
const TOKEN = process.env.E2E_APP_TOKEN;
const FULL = process.env.E2E_FULL_STACK;

test.describe("text to 3D", () => {
  test.skip(!TOKEN || !FULL, "Tam yığın (Redis + worker) gerekir");

  test("metinle tasarla → ilerleme → designer'da mesh", async ({ page }) => {
    const fatal: string[] = [];
    page.on("pageerror", (e) => fatal.push(e.message));
    page.on("console", (m) => {
      if (m.text().includes("Context Lost")) fatal.push(m.text());
    });

    await page.goto("/login");
    await page.getByPlaceholder("Bearer token").fill(TOKEN!);
    await page.getByRole("button", { name: "Giriş" }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    await page.getByRole("button", { name: "+ Yeni Tasarım" }).click();
    await page.getByRole("button", { name: /Metinle tasarla/ }).click();
    await page.locator("textarea").fill("kırmızı çiçekli bluz");
    await page.getByRole("button", { name: "Oluştur" }).click();

    // ilerleme → designer (placeholder ~2-3sn)
    await expect(page).toHaveURL(/\/design\//, { timeout: 30_000 });
    await expect(page.locator("canvas")).toBeVisible();
    await page.waitForTimeout(2000);
    expect(fatal, fatal.join("\n")).toEqual([]);
  });
});
