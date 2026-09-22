// Verifies the mic-permission-denied error path in a real browser.
import { chromium } from "playwright";

const url = process.argv[2] || "http://localhost:5173";

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
});
// No "microphone" permission granted, and no fake-ui flag -> getUserMedia rejects.
const context = await browser.newContext();
const page = await context.newPage();
await page.goto(url);
await page.waitForSelector("text=Start");
await page.click("text=Start");

await page.waitForSelector('[role="alert"]', { timeout: 15000 });
const text = await page.$eval('[role="alert"]', (el) => el.textContent);
console.log("[ok] error banner shown:", text);

await browser.close();
