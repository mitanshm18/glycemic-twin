// Renders the submission HTML sources to PDF (and PNG pages) with the installed Google Chrome.
//   node docs/submission-src/render.mjs <page.html> <out.pdf> [png-prefix] [--slides]
// Uses Playwright from web/node_modules; nothing is downloaded.
import { createRequire } from "node:module";
import path from "node:path";
const require = createRequire(path.resolve("web/package.json"));
const { chromium } = require("@playwright/test");

const [src, pdf, pngPrefix] = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const slides = process.argv.includes("--slides");
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: slides ? 1920 : 1600, height: slides ? 1080 : 1000 }, deviceScaleFactor: 2 });
await page.goto("file://" + path.resolve(src));
await page.evaluate(() => document.fonts.ready);
await page.pdf({ path: pdf, preferCSSPageSize: true, printBackground: true });
if (pngPrefix) {
  const els = slides ? await page.$$(".slide") : [await page.$(".page")];
  for (let i = 0; i < els.length; i++) {
    await els[i].screenshot({ path: `${pngPrefix}-${String(i + 1).padStart(2, "0")}.png` });
  }
  console.log(`${els.length} PNG page(s)`);
}
await browser.close();
console.log("wrote", pdf);
