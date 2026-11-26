import path from "node:path";
import {randomUUID,createHash} from "node:crypto";
import {spawn} from "node:child_process";
import {mkdir, link, open, readFile, readdir, stat} from "node:fs/promises";
import {setTimeout as delay} from "node:timers/promises";
import {withLease} from "./lease.js";
import {home as root} from "./runtime.js";

function directory(id) {
  if (!/^[0-9a-f-]{36}$/.test(id)) throw Error("会话编号无效");
  return path.join(root, "sessions", id);
}
export async function save(file, object, {exclusive=false}={}) {
  // Append a complete record in one write. A legacy file or torn tail may
  // lack its final newline; terminate that tail without changing earlier bytes.
  const fd=await open(file,exclusive?"ax+":"a+",0o600);
  try{
    const {size}=await fd.stat();
    const tail=Buffer.alloc(1);
    if(size)await fd.read(tail,0,1,size-1);
    const prefix=size && tail[0]!==10 ? "\n" : "";
    const bytes=Buffer.from(prefix+JSON.stringify(object)+"\n");
    const {bytesWritten}=await fd.write(bytes);
    if(bytesWritten!==bytes.length)throw Error("状态快照未写完整，请只读核对");
    await fd.sync();
  }finally{await fd.close();}
}
export function normalizeReceipt(value) {
  if (value?.state === "receipt" && value.verified === false)
    return {...value,state:"uncertain",next:"recover"};
  if (value?.state === "receipt" && value.next === "recover") {
    const {next, reason, ...receipt} = value;
    return receipt;
  }
  if (value?.state === "receipt" && value.reason) {
    const {reason, ...receipt} = value;
    return receipt;
  }
  return value;
}
export async function read(file) {
  for(let attempt=0;;attempt++){
    try{return lastSnapshot(await readFile(file,"utf8"));}
    catch(e){
      if(e.code==="ENOENT")return null;
      // A competing creator can be between exclusive open and its first append.
      if(!(e instanceof SyntaxError)||attempt===3)throw e;
      await delay(30);
    }
  }
}
function lastSnapshot(text) {
  // Snapshots are single-line objects. Old single-JSON files may span lines.
  // Reading backwards also recovers a previous complete record after a crash.
  let end=text.trimEnd().length;
  while(end>0){
    const start=text.lastIndexOf("\n",end-1)+1;
    const line=text.slice(start,end);
    if(start===0 || line.startsWith("{") || line.startsWith("[")){
      try{return normalizeReceipt(JSON.parse(line));}catch{}
    }
    if(/[}\]]\s*$/.test(line)){
      try{return normalizeReceipt(JSON.parse(text.slice(0,end)));}catch{}
    }
    end=start-1;
  }
  throw new SyntaxError("状态文件没有完整 JSON 快照，请只读核对");
}
// Only a new session may reuse a removed receipt; needs_user was canceled before send.
export function availableSubmission(record, session) {
  return !record || record.state === "needs_user" || (record.state === "removed" && record.session !== session);
}
export async function reserveSubmission(marker, session, observed, pending) {
  const lock = marker + ".reserve";
  await withLease("submission:"+path.basename(marker),async owner=>{
    // The permanent reservation also excludes legacy writers that use open("wx").
    const stamp=marker+"."+owner.token+".claim";
    let prior=await read(lock).catch(e=>{if(e instanceof SyntaxError)return {};throw e;});
    if(!prior){
      await save(stamp,{kind:"crosspost-submission-v2",token:owner.token});
      try{await link(stamp,lock);}catch(e){if(e.code!=="EEXIST")throw e;}
      prior=await read(lock);
    }
    if(!["crosspost-submission-v1","crosspost-submission-v2"].includes(prior?.kind))
      throw Error("旧进程正在登记本次提交，保留现场只读核对");
    const current=await read(marker);
    if(!availableSubmission(current,session)||JSON.stringify(current)!==JSON.stringify(observed))
      throw Error("该素材的提交记录发生变化，请续查原稿");
    await save(marker,{...pending,session});
  });
}
async function answer(dir, key, timeout) {
  const end = Date.now() + timeout;
  do {
    const value = await read(path.join(dir,key));
    if (value) return value;
    const ended = await read(path.join(dir,"end"));
    if (ended) throw Error(ended.error || "分发会话已结束");
    await delay(120);
  } while (Date.now() < end);
  throw Error("等待响应超时；保留会话并查询请求 "+key+" 的结果");
}
export async function start(cli, job) {
  if(!job)throw Error("start 需要任务 JSON");
  const bytes=await readFile(job);
  let seed=createHash("sha256").update(path.resolve(cli)).update(bytes).digest("hex");
  await mkdir(path.join(root,"sessions"),{recursive:true,mode:0o700});
  for (;;) {
    const key=seed.slice(0,32);
    const id=[key.slice(0,8),key.slice(8,12),key.slice(12,16),key.slice(16,20),key.slice(20)].join("-");
    const dir=directory(id);
    try {await mkdir(dir,{mode:0o700});}
    catch(e) {
      if(e.code!=="EEXIST")throw e;
      const ended=await read(path.join(dir,"end")),ready=await read(path.join(dir,"ready"));
      let active=false;
      if(!ended && ready){try{process.kill(ready.pid,0);active=true;}catch(err){if(err.code!=="ESRCH")throw err;}}
      if(active)return {session:id,...ready,reused:true};
      if(!ended && !ready && Date.now()-(await stat(dir)).mtimeMs<60000)
        return {session:id,...await answer(dir,"ready",60000),reused:true};
      seed=createHash("sha256").update(seed).digest("hex");
      continue;
    }
    try {
      const child=spawn(process.execPath,[cli,"worker",id,path.resolve(job)],{stdio:"ignore",detached:true,windowsHide:true});
      await new Promise((ok,fail)=>{child.once("spawn",ok);child.once("error",fail);});
      child.unref();
    }catch(e){await end(id,e.message);throw e;}
    return {session:id,...await answer(dir,"ready",60000)};
  }
}
export async function send(id, file) {
  const dir=directory(id), cmd=typeof file==="string"?await read(file):file;
  if (!cmd?.op) throw Error("动作 JSON 缺 op");
  const ready=await answer(dir,"ready",2000);
  if(await read(path.join(dir,"end"))) throw Error("会话已结束");
  try {process.kill(ready.pid,0);} catch {throw Error("分发进程已退出，请重新核对后台状态");}
  const key=Date.now()+"-"+randomUUID(), result=key+".result";
  await save(path.join(dir,key+".request"),cmd);
  try {return await answer(dir,result,360000);}
  catch(e){throw Error(e.message+"；使用 result "+id+" "+key+" 查询，勿重新发送该动作");}
}
export async function result(id,key){
  if (!/^\d+-[0-9a-f-]{36}$/.test(key)) throw Error("请求编号无效");
  return await answer(directory(id),key+".result",5000);
}
export async function serve(id, ready, handle) {
  const dir=directory(id);
  await save(path.join(dir,"ready"),{...ready,pid:process.pid});
  const claimed=new Set();
  let last=Date.now();
  while (Date.now()-last<3600000) {
    const files=(await readdir(dir)).filter(n=>n.endsWith(".request")&&!claimed.has(n)).sort();
    if (!files.length) {await delay(120); continue;}
    for (const name of files) {
      const file=path.join(dir,name), cmd=await read(file);
      try{await link(file,file+".claimed");}
      catch(e){if(e.code!=="EEXIST")throw e;claimed.add(name);continue;}
      claimed.add(name);
      let response;
      try {response=await handle(cmd);} catch(e){response=e.handoff || {error:e.message.split("\n").slice(0,4).join(" ")};}
      await save(file.replace(/\.request$/,".result"),response);
      last=Date.now();
      if (cmd.op==="close") return;
    }
  }
}
export async function end(id,error) {await save(path.join(directory(id),"end"),{closed:true,error});}
