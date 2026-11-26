import path from "node:path";
import {mkdir, stat, readFile, writeFile, realpath} from "node:fs/promises";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {chrome, home, browserEngine} from "./runtime.js";

import {read} from "./control.js";

const load = createRequire(path.join(home, "runtime", "package.json"));
const moduleFile = await realpath(fileURLToPath(import.meta.url));
const here = path.dirname(moduleFile);
const loadJson = async file => JSON.parse(await readFile(file, "utf8"));
const fingerprint = async file => {
  const s = await stat(file);
  return [file, s.dev, s.ino, s.size, s.mtimeMs];
};

export async function environment({cache=false}={}) {
  const profile = path.join(home, "profile");
  const result = {ready:false, profile, node:{version:process.versions.node, file:process.execPath}, chrome:null, playwright:null, accounts:{}, needs:[]};
  if (Number(process.versions.node.split(".")[0]) < 20) result.needs.push("安装 Node.js 20 或更新的 LTS 版");
  try {result.chrome = await chrome();} catch (e) {result.needs.push(e.message);}
  const required = (await loadJson(path.join(here, "package.json"))).dependencies["playwright-core"];
  let entry, manifest;
  try {
    manifest = load.resolve("playwright-core/package.json");
    entry = load.resolve("playwright-core");
    result.playwright = (await loadJson(manifest)).version;
  } catch {}
  if (result.playwright !== required || !entry) result.needs.push("运行 setup 安装锁定的 playwright-core " + required);
  for (const platform of ["douyin","xhs","bilibili","channels","mp"]) {
    try {
      const account = await read(path.join(home, "accounts", platform + ".json"));
      if (typeof account?.display === "string") result.accounts[platform] = account.uid ? {display:account.display, uid:account.uid} : account.display;
    } catch (e) {if (e.code !== "ENOENT") throw e;}
  }
  if (result.needs.length) return result;
  if (cache) await mkdir(profile, {recursive:true,mode:0o700});
  const bound = await realpath(profile).catch(e => {if(e.code==="ENOENT")return null;throw e;});
  if (!bound) {browserEngine();return {...result,ready:true,cached:false};}
  const s = await stat(bound);
  const key = JSON.stringify([required, process.versions.node, bound, s.dev, s.ino,
    ...await Promise.all([result.chrome,process.execPath,manifest,entry,path.join(here,"package-lock.json")].map(fingerprint))]);
  const state = path.join(home, "environment.json");
  const previous = await loadJson(state).catch(e => {if(!["ENOENT","EACCES","EPERM"].includes(e.code) && !(e instanceof SyntaxError)) throw e; return null;});
  if (previous?.key === key) return {...result,ready:true,cached:true};
  browserEngine();
  if (cache) {
    // Disposable setup cache. A partial write is a cache miss on the next check.
    await writeFile(state,JSON.stringify({key,profile:bound,checkedAt:new Date().toISOString()}),{mode:0o600})
      .catch(e => {if(!["EACCES","EPERM","EROFS","ENOSPC","EDQUOT"].includes(e.code))throw e;});
  }
  return {...result,ready:true,cached:false};
}
if (process.argv[1] && await realpath(process.argv[1]).catch(() => null) === moduleFile) {
  try {
    const value = await environment();
    console.log(JSON.stringify(value));
    if (!value.ready) process.exitCode = 1;
  } catch(e) {console.error(e.message);process.exitCode=1;}
}
