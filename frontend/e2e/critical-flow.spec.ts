import { test, expect } from "@playwright/test";

// .env'deki APP_TOKEN'ı ortamdan al (CI/local). Yoksa testi skip et.
const TOKEN = process.env.E2E_APP_TOKEN;

test.describe("critical flow", () => {
  test.skip(!TOKEN, "E2E_APP_TOKEN tanımlı değil");

  test("login → wizard → design → renk → kaydet → dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("Bearer token").fill(TOKEN!);
    await page.getByRole("button", { name: "Giriş" }).click();

    await expect(page).toHaveURL(/\/dashboard/);
    await page.getByRole("button", { name: "+ Yeni Tasarım" }).click();

    // Step 1: tür seç
    await page.getByText("Tişört", { exact: true }).click();
    // Step 2: ilk şablon
    await page.locator("button:has(img)").first().click();

    await expect(page).toHaveURL(/\/design\//);
    // 3D canvas mount oldu mu
    await expect(page.locator("canvas")).toBeVisible();

    // Renk değiştir (ikinci swatch)
    await page.locator('aside button[title]').nth(1).click();
    await page.getByRole("button", { name: "Kaydet" }).click();
    await expect(page.getByText("kaydedildi")).toBeVisible();

    // Dashboard'da görünür
    await page.getByRole("button", { name: "← Geri" }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator("text=tasarımı").first()).toBeVisible();
  });
});
