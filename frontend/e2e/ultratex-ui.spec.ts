import { test, expect } from "@playwright/test";

// "Görselden doku (UltraTex)": görsel seçip düğmeye basınca kaynak proje + görsel
// /generate/retexture-image'e gitmeli ve ilerleme sayfasına geçmeli. İstek yakalanır,
// gerçek iş kuyruğa girmez (UltraTex iki GPU'yu ~9 dk meşgul eder).
const TOKEN = process.env.E2E_APP_TOKEN;
const PROJECT = process.env.E2E_PROJECT_ID; // mesh'i olan herhangi bir tasarım

test.describe("texture from image (UltraTex)", () => {
  test.skip(!TOKEN || !PROJECT, "E2E_APP_TOKEN / E2E_PROJECT_ID yok");

  test("sends the source project and the chosen image, then shows progress", async ({ page }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    let body = "";
    await page.route("**/api/generate/retexture-image", async (route) => {
      body = route.request().postDataBuffer()?.toString("latin1") ?? "";
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ job_id: "e2e-job", project_id: "e2e-project", dress_job_id: null }),
      });
    });

    await page.addInitScript(() => localStorage.setItem("ui.lang", "tr"));
    await page.goto("/login");
    const tokenBox = page.getByPlaceholder("Bearer token");
    if (await tokenBox.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await tokenBox.fill(TOKEN!);
      await page.getByRole("button", { name: "Giriş" }).click();
    }
    await expect(page).toHaveURL(/\/dashboard/);

    await page.goto(`/design/${PROJECT}`);
    await expect(page.getByText("Görselden doku (UltraTex)")).toBeVisible({ timeout: 60_000 });

    const PNG_1x1 = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    );
    await page.getByTestId("imagetex-file").setInputFiles({ name: "kumas.png", mimeType: "image/png", buffer: PNG_1x1 });
    await page.getByTestId("imagetex-go").click();

    await expect(page).toHaveURL(/\/progress\/e2e-job\?project=e2e-project/);
    expect(body).toContain('name="source_project_id"');
    expect(body).toContain(PROJECT!);
    expect(body).toContain('filename="kumas.png"');
    expect(errors).toEqual([]);
  });
});
