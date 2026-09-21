/**
 * Measure the reviewer stat tiles across viewport widths and report any
 * value text that wraps to more than one line or overflows its tile.
 *
 * Usage: node scripts/measure_stat_tiles.mjs <requestId>
 */
import { chromium } from "playwright";

const requestId = process.argv[2];
const base = process.argv[3] ?? "http://localhost:3000";
if (!requestId) {
  console.error("usage: node scripts/measure_stat_tiles.mjs <requestId>");
  process.exit(1);
}

const WIDTHS = [1024, 1152, 1200, 1280, 1440, 1920];

const browser = await chromium.launch();
let problems = 0;

for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  await page.goto(`${base}/requests/${requestId}/review`, {
    waitUntil: "networkidle",
  });
  await page.waitForTimeout(1200);

  const tiles = await page.evaluate(() => {
    // Each tile is a bordered card whose first <p> is the label.
    const cards = Array.from(document.querySelectorAll("div.rounded-card"));
    return cards
      .map((card) => {
        const ps = card.querySelectorAll("p");
        if (ps.length < 2) return null;
        const label = ps[0].textContent?.trim() ?? "";
        const valueEl = ps[1];
        const value = valueEl.textContent?.trim() ?? "";
        const style = getComputedStyle(valueEl);
        const lineHeight = parseFloat(style.lineHeight) || 1;
        const lines = Math.round(valueEl.getBoundingClientRect().height / lineHeight);
        return {
          label,
          value,
          lines,
          valueWidth: Math.round(valueEl.scrollWidth),
          boxWidth: Math.round(valueEl.clientWidth),
          overflows: valueEl.scrollWidth > valueEl.clientWidth + 1,
        };
      })
      .filter((t) => t && ["Required Evidence", "Found", "Missing", "Validation", "Retrieval Sources", "Retry Count"].includes(t.label));
  });

  console.log(`\n=== ${width}px ===`);
  for (const tile of tiles) {
    const bad = tile.overflows || (tile.lines > 1 && !tile.value.includes(" "));
    if (bad) problems++;
    console.log(
      `  ${bad ? "BAD " : "ok  "} ${tile.label.padEnd(20)} "${tile.value}"` +
        `  lines=${tile.lines} text=${tile.valueWidth}px box=${tile.boxWidth}px`,
    );
  }
  await context.close();
}

await browser.close();
console.log(
  problems === 0
    ? "\nNo mid-word breaks and no overflow at any width."
    : `\n${problems} problem(s) found.`,
);
process.exit(problems === 0 ? 0 : 1);
