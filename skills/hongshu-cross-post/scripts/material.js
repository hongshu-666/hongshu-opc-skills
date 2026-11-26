import path from "node:path";
import { readdir, open, realpath, stat } from "node:fs/promises";
import { createReadStream } from "node:fs";
import { createHash } from "node:crypto";

export function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}
export async function hashFile(file) {
  const hash = createHash("sha256");
  for await (const block of createReadStream(file)) hash.update(block);
  return hash.digest("hex");
}
async function dimensions(file) {
  const fd = await open(file, "r");
  const buf = Buffer.alloc(512 * 1024);
  try {
    const { bytesRead: n } = await fd.read(buf);
    if (n >= 24 && buf.subarray(1, 4).toString() === "PNG")
      return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
    if (n >= 30 && buf.toString("ascii",0,4)==="RIFF" && buf.toString("ascii",8,12)==="WEBP") {
      const code=buf.toString("ascii",12,16);
      if (code==="VP8X") return [1+buf.readUIntLE(24,3),1+buf.readUIntLE(27,3)];
      if (code==="VP8 " && buf.readUIntBE(23,3)===0x9d012a) return [buf.readUInt16LE(26)&0x3fff,buf.readUInt16LE(28)&0x3fff];
      if (code==="VP8L" && buf[20]===0x2f) {const bits=buf.readUInt32LE(21);return [(bits&0x3fff)+1,((bits>>>14)&0x3fff)+1];}
    }
    if (buf.readUInt16BE(0) === 0xffd8) {
      let i = 2;
      while (i + 9 < n && buf[i] === 255) {
        if (buf[i + 1] === 255) {
          i++;
          continue;
        }
        if (
          [
            192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207,
          ].includes(buf[i + 1])
        )
          return [buf.readUInt16BE(i + 7), buf.readUInt16BE(i + 5)];
        const len = buf.readUInt16BE(i + 2);
        if (len < 2) break;
        i += len + 2;
      }
    }
    return null;
  } finally {
    await fd.close();
  }
}
export async function inventory(dir) {
  const folder = await realpath(dir);
  const entries = (await readdir(folder, { withFileTypes: true })).filter(
    (e) => e.isFile() && !e.name.startsWith("."),
  );
  const videos = entries
    .filter((e) => /\.(mp4|mov|m4v|webm)$/i.test(e.name))
    .map((e) => e.name);
  const images = [];
  for (const e of entries.filter((e) => /\.(jpe?g|png|webp)$/i.test(e.name))) {
    const size = await dimensions(path.join(folder, e.name));
    images.push({
      name: e.name,
      size,
      ratio: size ? aspect(size) : null,
      orientation: !size
        ? "未知"
        : size[0] > size[1]
          ? "横"
          : size[0] < size[1]
            ? "竖"
            : "方",
    });
  }
  return { folder, videos, images };
}
function aspect([width, height]) {
  const formats = [[4,3],[16,9],[9,16],[3,4],[1,1]];
  const pair = formats.find(([w,h]) => Math.abs(width*h/(height*w)-1) <= .008);
  return pair ? pair.join(":") : width + "×" + height;
}
const sourceHashes=new Map();
async function sourceHash(file){
  const before=await stat(file,{bigint:true});
  const token=[before.dev,before.ino,before.size,before.ctimeNs,before.mtimeNs].join("/");
  const cached=sourceHashes.get(file);
  if(cached?.token===token)return cached.hash;
  const hash=await hashFile(file),after=await stat(file,{bigint:true});
  if(token!==[after.dev,after.ino,after.size,after.ctimeNs,after.mtimeNs].join("/"))throw Error("读取期间素材发生变化");
  sourceHashes.set(file,{token,hash});return hash;
}
async function choose(items, role, ratios, specified, folder) {
  const matches = items.filter(i => ratios.includes(i.ratio));
  if (specified) {
    const item = matches.find(i => i.name === specified);
    if (!item) throw Error(role + " 需要 " + ratios.join(" 或 ") + " 的原图，请核实像素尺寸");
    return item.name;
  }
  // For identical copies prefer the shortest descriptive filename. Different artwork needs a choice.
  for (const ratio of ratios) {
    const same = matches.filter(i => i.ratio === ratio).sort((a,b)=>a.name.length-b.name.length);
    if (!same.length) continue;
    if (same.length === 1) return same[0].name;
    const signatures = await Promise.all(same.map(i=>sourceHash(path.join(folder,i.name))));
    if (new Set(signatures).size === 1) return same[0].name;
    throw Error(role + " 有不同版本，请比较缩略图并指定：" + same.map(i=>i.name).join("、"));
  }
  throw Error(role + " 缺少 " + ratios.join(" 或 ") + " 封面");
}
const coverRoles={douyin:["portrait","landscape"],xhs:["portrait"],channels:["portrait"],bilibili:["landscape","wide"]};
export function platformAssets(assets,k){
  return Object.fromEntries(Object.entries(assets).filter(([role])=>role==="video" || coverRoles[k]?.includes(role)));
}
export async function material(job) {
  const {folder,images,videos} = await inventory(job.folder);
  const roles = new Set(job.targets.flatMap(t=>coverRoles[t.platform]||[]));
  const selected = {};
  async function add(role, file) {
    const real = await realpath(file);
    const bytes = (await stat(real)).size;
    if (!bytes) throw Error("空文件：" + file);
    selected[role] = {file:real,name:path.basename(real),bytes,sha256:await sourceHash(real)};
  }
  const name=job.video ?? (videos.length===1?videos[0]:undefined);
  if (!(job.videoPath && path.isAbsolute(job.videoPath)) && !videos.includes(name))
    throw Error("未找到选定视频文件");
  const video = job.videoPath || path.join(folder,name);
  if (!/\.(mp4|mov|m4v|webm)$/i.test(video)) throw Error("视频格式无法识别");
  await add("video",video);
  for (const [role,ratios] of [["portrait",["9:16","3:4"]],["landscape",["4:3"]],["wide",["16:9"]]]) {
    if (!roles.has(role)) continue;
    const name = await choose(images,role,ratios,job[role],folder);
    await add(role,path.join(folder,name));
  }
  return selected;
}
