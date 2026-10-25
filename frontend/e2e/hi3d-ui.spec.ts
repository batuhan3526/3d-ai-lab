import { test, expect } from "@playwright/test";

// "Şekli detaylandır (Hi3D)": düğmeye basınca kaynak proje hi3d-refine ile /generate/refine'a
// gitmeli ve ilerleme sayfasına geçmeli; lisansın istediği bağlantılı atıf görünmeli.
// İstek yakalanır, gerçek iş kuyruğa girmez.
const TOKEN = process.env.E2E_APP_TOKEN;
const PROJECT = process.env.E2E_PROJECT_ID; // mesh'i olan herhangi bir tasarım

test.describe("shape detail (Hi3D)", () => {
  test.skip(!TOKEN || !PROJECT, "E2E_APP_TOKEN / E2E_PROJECT_ID yok");

  test("sends the source project to hi3d-refine, then shows progress", async ({ page }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    let body: Record<string, unknown> = {};
    await page.route("**/api/generate/refine", async (route) => {
      body = route.request().postDataJSON();
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
    await expect(page.getByText("Şekli detaylandır (Hi3D)")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("link", { name: "Powered by Hi3D 1.0" })).toHaveAttribute("href", "https://www.hi3d.ai/");

    await page.getByTestId("hi3d-go").click();
    await expect(page).toHaveURL(/\/progress\/e2e-job\?project=e2e-project/);
    expect(body).toEqual({ source_project_id: PROJECT, engine_id: "hi3d-refine" });
    expect(errors).toEqual([]);
  });
});
