import path from "node:path";
import {readFile,readdir,realpath,stat} from "node:fs/promises";
import {createHash} from "node:crypto";
import {digest} from "./material.js";

const photoExt = /\.(png|jpe?g|webp)$/i;
const clean = text => String(text ?? "").replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").trim();
async function optional(file) {
  try {return clean(await readFile(file,"utf8"));}
  catch(e){if(e.code==="ENOENT")return "";throw e;}
}
function numbered(names){
  const entries = names.filter(n=>photoExt.test(n)&&!n.includes("总览")).map(name=>{
    const match=path.parse(name).name.match(/(?:^|[^\d])(\d+)(?:页)?$/u);
    return {name,n:match?Number(match[1]):null};
  });
  if(entries.length>1 && (entries.some(e=>e.n==null)||new Set(entries.map(e=>e.n)).size!==entries.length))
    throw Error("请提供正式图片页序，文件名无法唯一排序");
  entries.sort((a,b)=>a.n-b.n);
  if(entries.length>1 && entries.some((e,i)=>i && e.n!==entries[i-1].n+1))throw Error("正式图页码不连续，请核对缺页");
  return entries.map(e=>e.name);
}
export async function photoMaterial(job){
  const folder=await realpath(job.folder);
  const names=await readdir(folder),raw=await optional(path.join(folder,"制作记录.json"));
  const spec=raw?JSON.parse(raw):{},txt=await optional(path.join(folder,"发布文案.txt"));
  const separator=raw?"\n\n":"\n";
  const split=txt.indexOf(separator);
  const metaTitle=clean(spec.publish_title||spec.title),metaBody=clean(spec.publish_copy);
  const titleFromTxt=split>=0?txt.slice(0,split):(raw?"":txt);
  const hasHeader=titleFromTxt && (!metaTitle || titleFromTxt===metaTitle);
  const textBody=hasHeader?(split<0?"":txt.slice(split+separator.length)):txt;
  if(metaBody && txt && clean(metaBody)!==clean(textBody))throw Error("发布文案.txt 与制作记录的标题或正文不一致");
  const title=clean(job.title??(metaTitle||titleFromTxt)),body=clean(job.body??(metaBody||textBody));
  const topics=job.topics??[];
  if(!Array.isArray(topics)||topics.some(t=>typeof t!=="string"||!t||/[#\s]/u.test(t))||new Set(topics).size!==topics.length)throw Error("话题需逐项填写裸名称且不能重复");
  const existing=new Set(Array.from(body.matchAll(/(?:^|\s)#([^#\s，。！？、]+)/gu),m=>m[1]));
  const missing=topics.filter(t=>!existing.has(t)).map(t=>"#"+t);
  const caption=[body,missing.join(" ")].filter(Boolean).join("\n\n");
  if([...title].length>20 || [...caption].length>1000)throw Error("标题或含话题的正文超限："+[...title].length+"/20，"+[...caption].length+"/1000");
  if(job.targets?.some(t=>t.platform!=="douyin")&&!title)throw Error("小红书或公众号贴图缺标题");
  const pages=spec.result?.pages;
  if(raw && (!Array.isArray(pages)||!pages.length))throw Error("制作记录缺正式页清单，请核对 result.pages");
  const ordered=raw?pages.map((p,i)=>{
    if(p.physical_page!=null && p.physical_page!==i+1)throw Error("制作记录页序冲突");
    const n=String(p.file??"").split(/[\\/]/).pop();
    if(!n||!photoExt.test(n)||n.includes("总览"))throw Error("正式页记录包含无效文件或总览图");return n;
  }):numbered(names);
  if(ordered.length<1||ordered.length>18||new Set(ordered).size!==ordered.length)throw Error("正式图需为1–18张且无重复页名");
  const photos=[];
  for(const name of ordered){
    const file=await realpath(path.join(folder,name));
    if(path.dirname(file)!==folder)throw Error("正式图不在选定素材目录："+name);
    const st=await stat(file);
    if(!st.isFile()||!st.size||st.size>10000000)throw Error("图片无效或单张超过10 MB："+name);
    const bytes=await readFile(file);
    const valid=bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || bytes[0]===255 && bytes[1]===216 && bytes[2]===255 || bytes.toString("ascii",0,4)==="RIFF" && bytes.toString("ascii",8,12)==="WEBP";
    if(!valid)throw Error("文件内容不是支持的图片："+name);
    photos.push({file,name,bytes:st.size,sha256:createHash("sha256").update(bytes).digest("hex")});
  }
  return {title,body,caption,topics,photos,signature:digest(photos.map(p=>p.sha256))};
}
