import { test, expect } from "@playwright/test";

// Regresyon: görsel yükleyip modele tıklayınca decal yerleşmeli ve 3D canvas
// ÇÖKMEMELİ. Eski hata: prosedürel GLB'lerde NORMAL attribute yoktu, drei <Decal>
// -> DecalGeometry "undefined.getX" ile patlıyor, WebGL context kaybolup ekran
// karararıyordu. Ayrıca thumbnail <img> GET'i token'sız 401 dönüyordu.
const TOKEN = process.env.E2E_APP_TOKEN;

test.describe("decal placement", () => {
  test.skip(!TOKEN, "E2E_APP_TOKEN yok");

  test("uploading an image and clicking the model places a decal without crashing", async ({
    page,
  }) => {
    const fatal: string[] = [];
    page.on("pageerror", (err) => fatal.push(`[pageerror] ${err.message}`));
    page.on("console", (msg) => {
      const t = msg.text();
      if (msg.type() === "error" && !t.includes("Failed to load resource")) {
        fatal.push(`[console.error] ${t}`);
      }
      if (t.includes("Context Lost")) fatal.push(`[webgl] ${t}`);
    });
    page.on("response", (resp) => {
      if (resp.status() === 401) fatal.push(`[http 401] ${resp.request().method()} ${resp.url()}`);
    });

    const PNG_1x1 = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    );

    await page.goto("/login");
    await page.getByPlaceholder("Bearer token").fill(TOKEN!);
    await page.getByRole("button", { name: "Giriş" }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    await page.getByRole("button", { name: "+ Yeni Tasarım" }).click();
    await page.getByText("Tişört", { exact: true }).click();
    await page.locator("button:has(img)").first().click();
    await expect(page).toHaveURL(/\/design\//);
    await expect(page.locator("canvas")).toBeVisible();
    await page.waitForTimeout(1500);

    await page.locator('input[type="file"]').setInputFiles({
      name: "logo.png",
      mimeType: "image/png",
      buffer: PNG_1x1,
    });
    await expect(page.getByText(/Yerleştirme modu/)).toBeVisible();

    const box = await page.locator("canvas").boundingBox();
    if (!box) throw new Error("canvas boundingBox yok");
    await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.4);
    await page.waitForTimeout(2000);

    // Decal yerleşti (yerleştirme modu kapandı, listede logo var)
    await expect(page.getByText(/Yerleştirme modu/)).toHaveCount(0);
    await expect(page.locator("aside li:has-text('Logo')")).toHaveCount(1);
    // Canvas hâlâ ayakta (çökmedi)
    await expect(page.locator("canvas")).toBeVisible();
    expect(fatal, `Beklenmeyen hatalar:\n${fatal.join("\n")}`).toEqual([]);
  });
});
