// One-off manual verification script (not part of the automated test
// suite): drives the real app in a real headless Chromium using Chromium's
// fake-audio-capture device, to prove the actual getUserMedia ->
// AudioWorklet -> WebSocket -> backend -> transcript-render pipeline runs
// without errors in a real browser engine. This is NOT a substitute for
// testing with a real human voice through a real microphone (see
// README.md "Testing" for exact manual steps to do that) -- Chromium's
// fake device emits a synthetic tone, so it proves plumbing, not
// recognition accuracy.
import { chromium } from "playwright";

const url = process.argv[2] || "http://127.0.0.1:5173";
const fakeAudioWav = process.argv[3]; // optional: feed a real WAV as the "microphone" input

const args = [
  "--use-fake-device-for-media-stream",
  "--use-fake-ui-for-media-stream",
  "--allow-file-access-from-files",
];
if (fakeAudioWav) {
  args.push(`--use-file-for-fake-audio-capture=${fakeAudioWav}`);
}

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args,
});
const context = await browser.newContext({ permissions: ["microphone"] });
const page = await context.newPage();

const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push(String(err)));

const wsTextMessages = [];
page.on("websocket", (ws) => {
  console.log("[ws] opened", ws.url());
  ws.on("framesent", (f) => {
    if (typeof f.payload === "string") wsTextMessages.push({ dir: "sent", payload: f.payload });
  });
  ws.on("framereceived", (f) => {
    if (typeof f.payload === "string") wsTextMessages.push({ dir: "recv", payload: f.payload });
  });
  ws.on("close", () => console.log("[ws] closed"));
});

await page.goto(url);
await page.waitForSelector("text=Start");
await page.click("text=Start");

// Wait for the app to reach "Listening" (proves mic permission flow +
// AudioContext + AudioWorklet + WebSocket connect + backend session_start
// round-trip all succeeded).
try {
  await page.waitForSelector("text=Listening", { timeout: 15000 });
  console.log("[ok] reached Listening state");
} catch (err) {
  console.log("[fail] never reached Listening. Console errors so far:", consoleErrors);
  console.log("[debug] body text:", await page.$eval("body", (el) => el.innerText));
  throw err;
}

// Let the fake device stream its audio through
// capture -> resample -> WS -> backend -> transcript_event -> UI.
await page.waitForTimeout(9000);

const meterWidth = await page.$eval(".level-meter__fill", (el) => el.style.width);
console.log("[info] level meter width after 4s:", meterWidth);

await page.click("text=Stop");
await page.waitForSelector("text=Complete", { timeout: 15000 });
console.log("[ok] reached Complete state after Stop");

const transcriptText = await page.$eval("textarea.transcript-editor", (el) => el.value);
console.log("[info] final transcript textarea content:", JSON.stringify(transcriptText));

console.log("[ws] text messages exchanged:", wsTextMessages.length);
for (const m of wsTextMessages) console.log(`  ${m.dir}: ${m.payload}`);

if (consoleErrors.length > 0) {
  console.log("[warn] browser console errors:", consoleErrors);
} else {
  console.log("[ok] no browser console errors");
}

await browser.close();
