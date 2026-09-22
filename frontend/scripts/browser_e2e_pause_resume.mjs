import { chromium } from "playwright";

const url = process.argv[2] || "http://localhost:5173";
const wav = process.argv[3];

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-audio-capture=${wav}`,
  ],
});
const context = await browser.newContext({ permissions: ["microphone"] });
const page = await context.newPage();
page.on("pageerror", (e) => console.log("[pageerror]", String(e)));

await page.goto(url);
await page.click("text=Start");
await page.waitForSelector("text=Listening", { timeout: 15000 });
console.log("[ok] listening");

await page.waitForTimeout(1500);
await page.click("text=Pause");
await page.waitForSelector("text=Paused", { timeout: 10000 });
console.log("[ok] paused");

const timerAtPause = await page.$eval(".controls__timer", (el) => el.textContent);
await page.waitForTimeout(1500);
const timerStillPaused = await page.$eval(".controls__timer", (el) => el.textContent);
console.log("[info] timer at pause:", timerAtPause, "-> after 1.5s paused:", timerStillPaused);

await page.click("text=Resume");
await page.waitForSelector("text=Listening", { timeout: 10000 });
console.log("[ok] resumed");

await page.waitForTimeout(1500);
await page.click("text=Stop");
await page.waitForSelector("text=Complete", { timeout: 15000 });
console.log("[ok] complete after pause/resume/stop");

const text = await page.$eval("textarea.transcript-editor", (el) => el.value);
console.log("[info] transcript after pause/resume cycle:", JSON.stringify(text));

await browser.close();
