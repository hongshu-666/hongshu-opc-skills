import net from "node:net";
import path from "node:path";
import {randomUUID,createHash} from "node:crypto";
import {link,mkdir,readdir,readFile,realpath,stat,utimes,writeFile} from "node:fs/promises";
import {execFile} from "node:child_process";
import {promisify} from "node:util";
import {home} from "./runtime.js";

const locks=path.join(home,"locks");
const denied=e=>e?.code==="EPERM" || e?.code==="EACCES";
const busy=()=>Object.assign(Error("已有任务持有此锁，稍后续接"),{code:"BUSY"});
const run=promisify(execFile);

function pidExists(pid){
  if(!Number.isSafeInteger(pid) || pid<=0)return false;
  try{process.kill(pid,0);return true;}
  catch(e){if(e.code==="ESRCH")return false;if(denied(e))return true;throw e;}
}
// Only consult OS creation time for a stale pulse and still-live PID. A sleeping
// worker keeps its lock. If the OS conceals creation time, preserve ownership.
async function startedAfter(pid,mtime){
  try{
    const win=process.platform==="win32";
    const args=win?["-NoProfile","-NonInteractive","-Command",
      "([DateTimeOffset](Get-Process -Id "+pid+").StartTime).ToUnixTimeMilliseconds()"]:
      ["-p",String(pid),"-o","lstart="];
    const {stdout}=await run(win?"powershell.exe":"ps",args,{timeout:2000,windowsHide:true,env:{...process.env,LC_ALL:"C"}});
    const started=win?Number(stdout.trim()):Date.parse(stdout.trim());
    return started>mtime+2000;
  }catch{return false;}
}
async function ownsFile(owner){
  if(!/^[a-f0-9]{64}$/.test(owner.key) || !/^[a-f0-9-]{36}$/.test(owner.token))return false;
  const dir=path.join(locks,owner.key);
  if(owner.epoch!==undefined && (!Number.isSafeInteger(owner.epoch)||owner.epoch<1))return false;
  const file=owner.epoch ? path.join(dir,"epochs",String(owner.epoch)) : path.join(dir,owner.token+".json");
  try{
    const holder=JSON.parse(await readFile(file,"utf8"));
    if(holder.token!==owner.token || holder.pid!==owner.pid || !pidExists(holder.pid))return false;
    if(owner.epoch && await stat(file+".released").then(()=>true,e=>{if(e.code==="ENOENT")return false;throw e;}))return false;
    const pulse=Math.max(holder.heartbeat,(await stat(file)).mtimeMs);
    return Date.now()-pulse<15000 || !await startedAfter(holder.pid,pulse);
  }catch(e){if(e.code==="ENOENT")return false;throw e;}
}
export async function withFileLease(name,fn){
  await mkdir(locks,{recursive:true,mode:0o700});
  const key=createHash("sha256").update(await realpath(home)+"\0"+name).digest("hex");
  const dir=path.join(locks,key),epochs=path.join(dir,"epochs");
  await mkdir(epochs,{recursive:true,mode:0o700});
  // An old holder may already be inside its critical section during an upgrade.
  // The nonempty epochs directory also prevents a legacy client from replacing it.
  for(const entry of await readdir(dir)){
    if(entry==="epochs")continue;
    if(!/^[a-f0-9-]{36}\.json$/.test(entry))throw busy();
    let old;
    try{old=JSON.parse(await readFile(path.join(dir,entry),"utf8"));}catch(e){if(e.code==="ENOENT")continue;throw e;}
    if(old.key!==key || entry!==old.token+".json" || await ownsFile(old))throw busy();
  }
  const names=await readdir(epochs);
  const last=names.reduce((n,k)=>/^[1-9]\d*$/.test(k)?Math.max(n,Number(k)):n,0);
  if(last){
    const previous=JSON.parse(await readFile(path.join(epochs,String(last)),"utf8"));
    if(previous.epoch!==last || previous.key!==key || await ownsFile(previous))throw busy();
  }
  const owner={key,epoch:last+1,pid:process.pid,token:randomUUID(),heartbeat:Date.now()};
  const file=path.join(epochs,String(owner.epoch)),ticket=path.join(epochs,owner.token+".owner");
  // A hard link publishes the complete owner record exactly once for this epoch.
  // Racing clients that observed the same predecessor cannot both enter.
  await writeFile(ticket,JSON.stringify(owner),{flag:"wx",mode:0o600});
  try{await link(ticket,file);}catch(e){if(e.code==="EEXIST")throw busy();throw e;}
  const pulse=setInterval(()=>{const now=new Date();utimes(file,now,now).catch(()=>{});},2000);
  pulse.unref();
  try{return await fn(owner);}
  finally{clearInterval(pulse);await writeFile(file+".released",owner.token,{flag:"wx",mode:0o600});}
}
export async function withLease(name,fn){
  // All hosts acquire the same filesystem record, including those with TCP.
  return withFileLease(name,async owner=>{
    const port=20000+parseInt(owner.key.slice(0,8),16)%35000;
    const server=net.createServer(socket=>{
      socket.on("error",()=>{});
      socket.end(JSON.stringify({pid:owner.pid,token:owner.token}));
    });
    try{
      await new Promise((ok,fail)=>{
        server.once("error",fail);
        server.listen({host:"127.0.0.1",port,exclusive:true},ok);
      });
    }catch(e){
      if(denied(e))return fn(owner);
      if(e.code==="EADDRINUSE")throw busy();
      throw e;
    }
    try{return await fn({...owner,port});}
    finally{await new Promise(ok=>server.close(ok));}
  });
}
export async function alive(owner){
  if(!owner?.token || owner.released || !pidExists(owner.pid))return false;
  if(!owner.port)return ownsFile(owner);
  try{
    return await new Promise((resolve,reject)=>{
      const socket=net.connect(owner.port,"127.0.0.1");
      let bytes="";
      const done=v=>{socket.destroy();resolve(v);};
      socket.setTimeout(600,()=>done(false));
      socket.on("error",e=>{socket.destroy();reject(e);});
      socket.on("data",part=>{bytes+=part;if(bytes.length>256)done(false);});
      socket.on("end",()=>{
        try{const v=JSON.parse(bytes);done(v.pid===owner.pid && v.token===owner.token);}
        catch{done(false);}
      });
    });
  }catch(e){
    if(denied(e))return owner.key?ownsFile(owner):pidExists(owner.pid);
    if(e.code==="ECONNREFUSED" || e.code==="ECONNRESET")return false;
    throw e;
  }
}
