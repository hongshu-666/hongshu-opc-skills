import { homedir, platform } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { mkdir, readFile, copyFile, access } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";

const here = path.dirname(fileURLToPath(import.meta.url));
const appData =
  platform() === "darwin"
    ? path.join(homedir(), "Library", "Application Support")
    : platform() === "win32"
      ? process.env.LOCALAPPDATA || path.join(homedir(), "AppData", "Local")
      : process.env.XDG_DATA_HOME || path.join(homedir(), ".local", "share");
export const home = path.resolve(process.env.CROSSPOST_HOME || path.join(appData, "HongshuCrosspost"));
export const root = path.resolve(process.env.CROSSPOST_DATA || home);
const runtime = path.join(home, "runtime");
const requireRuntime = createRequire(path.join(runtime, "package.json"));
const pinned = JSON.parse(await readFile(path.join(here, "package.json")))
  .dependencies["playwright-core"];

export function browserEngine() {
  if (requireRuntime("playwright-core/package.json").version !== pinned)
    throw Error("发布工具版本需要更新，请运行 setup");
  return requireRuntime("playwright-core").chromium;
}
export function chromePath() {
  if (platform() === "darwin")
    return [
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      path.join(
        homedir(),
        "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      ),
    ];
  if (platform() === "win32")
    return [
      process.env.PROGRAMFILES,
      process.env["PROGRAMFILES(X86)"],
      process.env.LOCALAPPDATA,
    ]
      .filter(Boolean)
      .map((x) =>
        path.join(x, "Google", "Chrome", "Application", "chrome.exe"),
      );
  return ["/usr/bin/google-chrome", "/opt/google/chrome/chrome"];
}
export async function chrome() {
  for (const file of chromePath()) {
    try {
      await access(file);
      return file;
    } catch {}
  }
  throw Error("请从 https://www.google.cn/chrome/ 安装 Chrome，然后继续");
}
export async function setup() {
  const browser = await chrome();
  try {
    browserEngine();
  } catch {
    await mkdir(runtime, { recursive: true, mode: 0o700 });
    for (const name of ["package.json", "package-lock.json"])
      await copyFile(path.join(here, name), path.join(runtime, name));
    const rel =
      platform() === "win32"
        ? "node_modules/npm/bin/npm-cli.js"
        : "../lib/node_modules/npm/bin/npm-cli.js";
    const npm = path.resolve(path.dirname(process.execPath), rel);
    await access(npm).catch(() => {
      throw Error(
        "此 Node 缺少配套 npm，请选择带 npm 的 Node LTS 安装目录后重试",
      );
    });
    const install=(registry)=>spawnSync(process.execPath,[
      npm,"ci","--ignore-scripts","--no-audit","--no-fund","--fetch-retries=1",
      "--fetch-timeout=20000","--registry="+registry,"--replace-registry-host=always","--cache",path.join(runtime,"cache")
    ],{cwd:runtime,encoding:"utf8",maxBuffer:4*1024*1024});
    let run=install("https://registry.npmjs.org");
    if(run.status!==0 && /EAI_AGAIN|ETIMEDOUT|ENOTFOUND|ECONNRESET|ECONNREFUSED|ERR_SOCKET_TIMEOUT|HTTP 50[234]/i.test(run.stderr||""))
      run=install("https://registry.npmmirror.com");
    if(run.error || run.status!==0) throw Error("依赖安装失败："+(run.error?.code || (run.stderr||"").match(/(?:code|errno) (\w+)/)?.[1] || run.status));
    browserEngine();
  }
  return { browser, playwright: pinned };
}
const quietContexts = new WeakSet();
export async function requestHuman(page, message) {
  if (quietContexts.has(page.context())) {
    const error = Error(message);
    error.handoff = {status:"needs_user", message, requiresVisibleLogin:true, pageKept:false};
    throw error;
  }
  await page.bringToFront();
}
export async function launch({ visible = false } = {}) {
  const executablePath = await chrome();
  await mkdir(home, { recursive: true, mode: 0o700 });
  const context = await browserEngine().launchPersistentContext(
    path.join(home, "profile"),
    {
      executablePath,
      headless: !visible,
      chromiumSandbox: true,
      viewport: visible ? null : { width: 1440, height: 900 },
      acceptDownloads: false,
      args: ["--no-first-run", "--no-default-browser-check"],
    },
  );
  if (!visible) quietContexts.add(context);
  context.setDefaultTimeout(8000);
  return context;
}

// Open a background tab in the local persistent Chrome that owns the upload.
export async function backgroundTab(context) {
  const anchor = context.pages().find(page => !page.isClosed());
  if (!anchor) return context.newPage();
  const connection = await context.newCDPSession(anchor);
  const url = "about:blank#crosspost-" + randomUUID();
  try {
    const [page] = await Promise.all([
      context.waitForEvent("page", { predicate: tab => tab.url() === url }),
      connection.send("Target.createTarget", { url, background: true, newWindow: false }),
    ]);
    return page;
  } finally {
    await connection.detach();
  }
}
