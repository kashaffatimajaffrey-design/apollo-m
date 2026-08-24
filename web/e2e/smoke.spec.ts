import { test, expect } from "@playwright/test";

test("the dashboard shell renders server-side", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /community instability/i }),
  ).toBeVisible();
  // Anchored to the start of the intro paragraph: the footer describes the same
  // system, so an unscoped phrase match would resolve to two nodes and fail
  // strict mode.
  await expect(
    page.getByText(/^The same rows the Streamlit dashboard/i),
  ).toBeVisible();
});

test("an unconfigured project explains itself instead of crashing", async ({
  page,
}) => {
  // A fresh clone has no .env.local. Both streamed sections should degrade to
  // setup instructions rather than throwing, and the header must still render.
  await page.goto("/");
  await expect(
    page.getByText(/Supabase is not answering yet/i).first(),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /^Sign in$/ })).toBeVisible();
});

test("the sign-in form is reachable and labelled", async ({ page }) => {
  await page.goto("/login");
  // getByLabel, not a CSS selector: if the label/control association breaks,
  // this fails — which is the accessibility bug worth catching.
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("the form switches to sign-up", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /create one/i }).click();
  await expect(
    page.getByRole("heading", { name: /create an account/i }),
  ).toBeVisible();
});

test("the page renders without JavaScript", async ({ browser }) => {
  // The whole reason for Server Components and form actions: the markup is
  // complete before hydration. If this fails, something has drifted to the
  // client that did not need to be there.
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /community instability/i }),
  ).toBeVisible();
  await context.close();
});
