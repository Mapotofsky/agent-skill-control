#!/usr/bin/env node

import { createServer } from "node:http";
import { createReadStream, existsSync, promises as fs } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) {
      continue;
    }
    const key = value.slice(2);
    const next = argv[index + 1];
    if (next && !next.startsWith("--")) {
      parsed[key] = next;
      index += 1;
    } else {
      parsed[key] = true;
    }
  }
  return parsed;
}

function mimeType(filename) {
  const extension = path.extname(filename).toLowerCase();
  return {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
  }[extension] ?? "application/octet-stream";
}

async function loadPlaywright() {
  try {
    const configuredModule = process.env.VIDEO_EVIDENCE_PLAYWRIGHT_MODULE;
    const entry = configuredModule || require.resolve("playwright");
    const module = await import(pathToFileURL(entry).href);
    const browserPath = module.chromium.executablePath();
    await fs.access(browserPath);
    return { available: true, module, browserPath };
  } catch (error) {
    return { available: false, error: `${error.name}: ${error.message}` };
  }
}

async function serveMedia(inputPath) {
  const stat = await fs.stat(inputPath);
  const server = createServer((request, response) => {
    if (request.url !== "/media") {
      response.writeHead(404).end();
      return;
    }
    const range = request.headers.range;
    const headers = {
      "Accept-Ranges": "bytes",
      "Content-Type": mimeType(inputPath),
    };
    if (!range) {
      response.writeHead(200, { ...headers, "Content-Length": stat.size });
      createReadStream(inputPath).pipe(response);
      return;
    }
    const match = /bytes=(\d*)-(\d*)/.exec(range);
    if (!match) {
      response.writeHead(416, { "Content-Range": `bytes */${stat.size}` }).end();
      return;
    }
    const start = match[1] ? Number(match[1]) : 0;
    const end = match[2] ? Math.min(Number(match[2]), stat.size - 1) : stat.size - 1;
    if (start > end || start >= stat.size) {
      response.writeHead(416, { "Content-Range": `bytes */${stat.size}` }).end();
      return;
    }
    response.writeHead(206, {
      ...headers,
      "Content-Range": `bytes ${start}-${end}/${stat.size}`,
      "Content-Length": end - start + 1,
    });
    createReadStream(inputPath, { start, end }).pipe(response);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Could not allocate a local media server port.");
  }
  return { server, url: `http://127.0.0.1:${address.port}/media` };
}

async function loadVideo(page, url) {
  await page.setContent('<video id="video" muted playsinline></video>');
  return page.evaluate(async (mediaUrl) => {
    const video = document.querySelector("#video");
    video.src = mediaUrl;
    video.load();
    await new Promise((resolve, reject) => {
      video.addEventListener("loadedmetadata", resolve, { once: true });
      video.addEventListener("error", () => reject(new Error(video.error?.message ?? "video load error")), {
        once: true,
      });
    });
    return { duration: video.duration, width: video.videoWidth, height: video.videoHeight };
  }, url);
}

async function captureFrame(page, timestamp) {
  return page.evaluate(async (requestedTime) => {
    const video = document.querySelector("#video");
    const duration = Number.isFinite(video.duration) ? video.duration : requestedTime;
    const safeTime = Math.min(Math.max(0, requestedTime), Math.max(0, duration - 0.05));
    if (Math.abs(video.currentTime - safeTime) > 0.01) {
      await new Promise((resolve, reject) => {
        video.addEventListener("seeked", resolve, { once: true });
        video.addEventListener("error", () => reject(new Error(video.error?.message ?? "seek error")), {
          once: true,
        });
        video.currentTime = safeTime;
      });
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.92);
  }, timestamp);
}

async function check() {
  const playwright = await loadPlaywright();
  if (!playwright.available) {
    console.log(JSON.stringify({ available: false, error: playwright.error }));
    return;
  }
  console.log(JSON.stringify({ available: true, browser_path: playwright.browserPath }));
}

async function capture(args) {
  for (const name of ["input", "request", "output", "result"]) {
    if (typeof args[name] !== "string") {
      throw new Error(`Missing required --${name} argument.`);
    }
  }
  const inputPath = path.resolve(args.input);
  const outputPath = path.resolve(args.output);
  const resultPath = path.resolve(args.result);
  if (!existsSync(inputPath)) {
    throw new Error(`Input file does not exist: ${inputPath}`);
  }
  const request = JSON.parse(await fs.readFile(path.resolve(args.request), "utf8"));
  if (!Array.isArray(request)) {
    throw new Error("Playwright request must be an array.");
  }

  const playwright = await loadPlaywright();
  if (!playwright.available) {
    throw new Error(`Playwright unavailable: ${playwright.error}`);
  }
  await fs.mkdir(outputPath, { recursive: true });
  const media = await serveMedia(inputPath);
  let browser;
  try {
    browser = await playwright.module.chromium.launch({ headless: true });
    const page = await browser.newPage();
    const metadata = await loadVideo(page, media.url);
    const frames = [];
    for (const item of request) {
      const timestamp = Number(item.timestamp_seconds);
      const filename = String(item.filename ?? "");
      if (!Number.isFinite(timestamp) || !filename || path.basename(filename) !== filename) {
        throw new Error("Invalid frame request.");
      }
      const dataUrl = await captureFrame(page, timestamp);
      const comma = dataUrl.indexOf(",");
      if (comma < 0) {
        throw new Error(`Browser did not return an image for ${timestamp}s.`);
      }
      await fs.writeFile(path.join(outputPath, filename), Buffer.from(dataUrl.slice(comma + 1), "base64"));
      frames.push({ timestamp_seconds: timestamp, file: filename });
    }
    await fs.writeFile(
      resultPath,
      `${JSON.stringify({ backend: "playwright", metadata, frames }, null, 2)}\n`,
      "utf8",
    );
  } finally {
    if (browser) {
      await browser.close();
    }
    await new Promise((resolve) => media.server.close(resolve));
  }
}

const args = parseArgs(process.argv.slice(2));
if (args.check) {
  await check();
} else {
  try {
    await capture(args);
  } catch (error) {
    console.error(`${error.name}: ${error.message}`);
    process.exitCode = 1;
  }
}
