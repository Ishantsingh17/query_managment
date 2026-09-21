/**
 * Capture the four screens for visual comparison against UI_SCREENS/.
 *
 * Usage: node scripts/screenshot.mjs <requestId> [outDir]
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const requestId = process.argv[2];
const outDir = process.argv[3] ?? "screenshots";

if (!requestId) {
  console.error("usage: node scripts/screenshot.mjs <requestId> [outDir]");
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });

// Matches the mockups' apparent design width.
const VIEWPORT = { width: 1440, height: 1000 };

const SHOTS = [
  { name: "1-audit-request", path: "/audit" },
  { name: "2-request-detail", path: `/requests/${requestId}` },
  { name: "3-review-package", path: `/requests/${requestId}/review` },
  { name: "4-final-package", path: `/requests/${requestId}/package` },
  { name: "5-requests-list", path: "/requests" },
  { name: "6-use-cases", path: "/use-cases" },
];

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: 2,
});
const page = await context.newPage();

const problems = [];
page.on("console", (message) => {
  if (message.type() === "error") problems.push(`console: ${message.text()}`);
});
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

for (const shot of SHOTS) {
  const url = `http://localhost:3000${shot.path}`;
  await page.goto(url, { waitUntil: "networkidle" });
  // Let client-side fetches settle and any spinner resolve.
  await page.waitForTimeout(1200);
  await page.screenshot({
    path: `${outDir}/${shot.name}.png`,
    fullPage: true,
  });
  const heading = await page
    .locator("h1")
    .first()
    .textContent()
    .catch(() => null);
  console.log(`captured ${shot.name.padEnd(20)} h1="${(heading ?? "").trim()}"`);
}

await browser.close();

if (problems.length) {
  console.log("\nBrowser problems detected:");
  for (const problem of [...new Set(problems)]) console.log("  - " + problem);
  process.exit(1);
}
console.log("\nNo console or page errors.");
