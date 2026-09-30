// Export the poster to PNG and a single-page PDF with the system Chrome.
// Usage: node export_poster.cjs   (needs playwright-core; set PLAYWRIGHT_CORE to its path if not installed locally)
const path = require("path");
const pw = require(process.env.PLAYWRIGHT_CORE || "playwright-core");

(async () => {
  const browser = await pw.chromium.launch({channel: "chrome", headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 1000}, deviceScaleFactor: 2});
    const url = "file:///" + path.resolve(__dirname, "FeedBench-Poster.local.html").replace(/\\/g, "/");
    await page.goto(url, {waitUntil: "networkidle"});
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    await page.screenshot({path: path.join(__dirname, "FeedBench-Poster.png"), fullPage: true});
    const height = await page.evaluate(() => Math.ceil(document.documentElement.scrollHeight));
    await page.pdf({path: path.join(__dirname, "FeedBench-Poster.pdf"), width: "1300px", height: height + "px",
                    printBackground: true, pageRanges: "1"});
    console.log("exported, height", height);
  } finally {
    await browser.close();
  }
})();
