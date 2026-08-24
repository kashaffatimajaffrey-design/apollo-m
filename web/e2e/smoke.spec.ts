import { existsSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

/**
 * Whether this checkout can reach a real Supabase project.
 *
 * Deliberately a filesystem check rather than `process.env`: Next.js loads
 * .env.local inside the dev-server subprocess, so the Playwright runner's own
 * environment is empty whether or not credentials exist. CI has no .env.local
 * because it is gitignored, so this is false there.
 */
const HAS_BACKEND = existsSync(path.join(process.cwd(), ".env.local"));

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

test("a backend that is missing or unmigrated degrades instead of crashing", async ({
  page,
}) => {
  // Only meaningful when there is no reachable, migrated backend — which is
  // exactly CI, since the runner holds no Supabase secrets. Locally, once
  // .env.local points at a real project with the schema applied, the app
  // correctly shows data instead, and asserting the fallback here would fail
  // for the right reason. Skipping beats loosening the assertion until it
  // passes in both states and guards neither.
  test.skip(
    HAS_BACKEND,
    "A backend is configured; the degraded path cannot be reached from here.",
  );
  // Two ways this fails in practice, and both must render rather than 500:
  // no credentials at all (a fresh clone, and CI, which holds no secrets), and
  // credentials that work against a project where the schema has not been
  // applied yet. Both surface the reason plus the next step, and the header
  // must survive either.
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

test("no cell renders NaN", async ({ page }) => {
  // Regression guard. The table once read a `toxicity_trend` column that the
  // view does not return; because the hand-written row type asserted the field
  // existed, the compiler stayed happy and every row rendered "NaN". Types
  // cannot catch a lie about the database's shape, so this asserts on what the
  // user actually sees.
  //
  // Valid in both states: with credentials the table renders real numbers, and
  // without them (CI holds no secrets) the setup message renders instead.
  // Neither should ever contain NaN.
  await page.goto("/");
  await expect(page.locator("body")).not.toContainText("NaN");
});

test("the dark palette survives a light-mode system preference", async ({
  page,
}) => {
  // Regression guard. globals.css shipped create-next-app's boilerplate — light
  // tokens plus a prefers-color-scheme:dark override — and that unlayered `body`
  // rule outranked Tailwind's layered `bg-[#0b0f14]` utility. Every component is
  // written for a dark ground, so on a machine set to light the page rendered
  // near-white text on white. It looked correct on any dark-mode machine, which
  // is why reading the text instead of the pixels missed it.
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");

  const bg = await page
    .locator("body")
    .evaluate((el) => getComputedStyle(el).backgroundColor);

  // Parse rather than string-match, so an equivalent notation still passes.
  const [r, g, b] = bg.match(/\d+/g)!.map(Number);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  expect(
    luminance,
    `body background was ${bg}, which is not dark`,
  ).toBeLessThan(0.25);
});

test("a failed sign-in points at sign-up instead of a dead end", async ({
  page,
}) => {
  // Needs a reachable Supabase project, since the message is derived from the
  // real auth error. CI holds no credentials, so it runs locally only.
  test.skip(!HAS_BACKEND, "No backend configured; auth cannot be exercised.");

  // Supabase returns one message for an unknown email and a wrong password, so
  // the form cannot be used to discover which emails are registered. Keeping
  // that property is right; leaving the raw "Invalid login credentials" was not,
  // because on a fresh project the real cause is almost always that no account
  // exists yet, and the message sends people to re-check a correct password.
  await page.goto("/login");
  await page
    .getByLabel("Email")
    .fill("definitely-not-registered@example.invalid");
  await page.getByLabel("Password").fill("whateverPassword123");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText(/do not match an account/i)).toBeVisible();
  // Still says nothing about whether that email exists.
  await expect(
    page.getByText(/no such user|not registered|unknown email/i),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: /create one/i })).toBeVisible();
});
