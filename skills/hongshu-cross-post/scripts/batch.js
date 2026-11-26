import path from "node:path";
import {randomUUID} from "node:crypto";
import {spawn} from "node:child_process";
import {mkdir,readFile,readdir,stat} from "node:fs/promises";
import {setTimeout as delay} from "node:timers/promises";
import {fileURLToPath} from "node:url";
import {home,launch,backgroundTab} from "./runtime.js";
import {read,save} from "./control.js";
import {digest} from "./material.js";
import {makePlan,assetHash,readAssets,pref,preferenceSnapshot} from "./plan.js";
import {executeJob} from "./item.js";
import {alive,withLease} from "./lease.js";
import {challengeOn} from "./account.js";
import {config} from "./platforms.js";

const batches=path.join(home,"batches");
function batchDir(id) {
  if(!/^[0-9a-f]{24}$/.test(id||""))throw Error("批次号无效");
  return path.join(batches,id);
}
const terminal=new Set(["done","partial","paused","failed","interrupted","busy"]);
function pair(job){return job.mode==="scheduled"?job.items[0]:job;}
export async function ledger() {
  const folder=path.join(home,"submissions");
  let files;
  try {files=await readdir(folder);}catch(e){if(e.code==="ENOENT")return [];throw e;}
  const rows=[];
  for(const f of files.filter(f=>f.endsWith(".json"))){
    const value=await read(path.join(folder,f));if(value)rows.push({file:f,...value});
  }
  return rows;
}
export function nextOperation(row,record) {
  if(record?.state==="receipt"&&record.verified!==false || record?.state==="removed" || row.state==="done")return "skip";
  if(record?.state==="needs_user")return "prepare";
  if(record || row.clicked || row.state==="uncertain")return "recover";
  return "prepare";
}
function message(e){return String(e?.message||e).split("Call log")[0].trim().slice(0,500);}
function publicView(id,state,plan) {
  const results=Object.entries(state.items||{}).map(([key,r])=>{
    const receipt=r.receipt;
    let result=r.reason||receipt?.status||receipt?.state||"";
    if(r.state==="done" && receipt?.state==="receipt" && receipt.scheduleAt){
      result=receipt.verified===true && receipt.scheduledAt
        ? "已核实定时发布 · "+receipt.scheduledAt : "预约分钟待核实";
    }
    if(receipt?.note)result=(result?result+"；":"")+receipt.note;
    return {key,account:plan?.rows.find(t=>t.key===key)?.account,state:r.state,result,next:r.next||""};
  });
  return {batchId:id,status:state.status,active:state.active,reason:state.reason,
    ...(["failed","paused","partial","interrupted"].includes(state.status)?{resumeCommand:"run --resume "+id}:{}),
    warnings:plan?.warnings||[],preferences:(plan?.rows||[]).filter(t=>Object.keys(t.applied).length).map(t=>({key:t.key,account:t.account,values:t.applied})),results};
}
async function status(id){
  const dir=batchDir(id),input=await read(path.join(dir,"input.json"));
  if(!input)throw Error("找不到批次 "+id);
  const state=await read(path.join(dir,"state.json"))||{status:"starting"};
  const owner=await read(path.join(dir,"owner.json"));
  if(state.status==="starting" && !owner && Date.now()-(await stat(path.join(dir,"input.json"))).mtimeMs>15000){
    state.status="interrupted";state.reason="任务尚未获得后台进程，使用 run --resume";
  }
  if(["running","login"].includes(state.status) && (!owner||Date.now()-owner.heartbeat>6000) && !await alive(owner)){
    state.status="interrupted";state.reason="后台进程已退出，使用 run --resume，已点击项只续查";
  }
  return publicView(id,state,await read(path.join(dir,"plan.json")));
}
async function waitStatus(id,seconds,attempt){
  const end=Date.now()+seconds*1000;
  for(;;){
    const result=await status(id);
    const notice=attempt && await read(path.join(batchDir(id),attempt+".json"));
    if(notice?.error)return {...result,status:"failed",reason:notice.error};
    if(notice?.busy)return {...result,status:notice.same?result.status:"busy",reason:notice.message};
    if((!attempt||notice) && (terminal.has(result.status)||result.status==="login") || Date.now()>=end)return result;
    await delay(Math.min(500,Math.max(1,end-Date.now())));
  }
}
async function start(id,dir,mode,seconds){
  const attempt=randomUUID();
  const cli=fileURLToPath(new URL("./publish.js",import.meta.url));
  const child=spawn(process.execPath,[cli,"batch-worker",id,mode,attempt],{stdio:"ignore",detached:true,windowsHide:true});
  await new Promise((ok,bad)=>{child.once("spawn",ok);child.once("error",bad);});
  child.unref(); return waitStatus(id,seconds,attempt);
}
async function writeOnce(file,value) {
  try{await save(file,value,{exclusive:true});return true;}
  catch(e){if(e.code!=="EEXIST")throw e;await read(file);return false;}
}
async function work(id,mode,attempt) {
  const dir=batchDir(id),stateFile=path.join(dir,"state.json"),planFile=path.join(dir,"plan.json"),ownerFile=path.join(dir,"owner.json");
  if(!/^[0-9a-f-]{36}$/.test(attempt)||!["new","resume"].includes(mode))throw Error("批次启动参数无效");
  const notice=path.join(dir,attempt+".json");
  try {await withLease("profile",async owner=>{
    let state=await read(stateFile)||{items:{}};
    if(state.status==="done" || mode==="new" && state.status && state.status!=="busy"){
      await save(notice,{attached:true});return;
    }
    let ctx,timer,pulse=Promise.resolve();
    const checkpoint=()=>save(stateFile,state);
    try{
      await save(ownerFile,owner);
      timer=setInterval(()=>{pulse=pulse.then(()=>save(ownerFile,{...owner,heartbeat:Date.now()})).catch(()=>{});},2000);
      state.status="running";delete state.reason;await checkpoint();await save(notice,{started:true});
      let plan=await read(planFile);
      if(!plan){
        plan=await makePlan(await read(path.join(dir,"input.json")),await read(path.join(dir,"preferences.json")));
        for(const t of plan.rows)state.items[t.key]={session:randomUUID(),state:"pending"};
        await checkpoint();await save(planFile,plan);
      }
      const interactive=mode==="resume" && Object.values(state.items).some(r=>r.state==="needs_login");
      const deferred=new Set();
      for(const t of plan.rows){
        const r=state.items[t.key],scope=JSON.stringify([t.platform,t.accountId]);
        const prior=(await ledger()).find(e=>e.session===r.session);
        const op=nextOperation(r,prior);
        if(op==="skip"){
          r.state="done";r.clicked=true;r.receipt=prior||r.receipt;delete r.reason;delete r.next;continue;
        }
        if(deferred.has(scope)){r.state="needs_login";r.reason="同账号等待集中扫码";r.next="resume";continue;}
        state.active=t.key;await checkpoint();
        let keeper;
        try{
          ctx??=await launch({visible:interactive});
          keeper=ctx.pages()[0]||await backgroundTab(ctx);
          const deadline=Date.now()+900000;
          for(;;){
            try{
              const assets=op==="prepare"?await readAssets(pair(t.job)):undefined;
              if(assets && assetHash(assets)!==t.signature)throw Error("素材已变化，请核对该项");
              const result=await executeJob(r.session,structuredClone(t.job),{
                execution:t.execution && structuredClone(t.execution),assets,context:ctx,recover:op==="recover",
                beforeSubmit:async()=>{
                  r.state="submitting";await checkpoint();
                }
              });
              if(result.next==="recover"||result.state==="uncertain"||result.verified===false)
                throw Error(result.reason||result.error||"已点击，待核实");
              const actual=(await ledger()).find(e=>e.session===r.session && e.state==="receipt");
              if(!actual)throw Error("尚无作品管理或草稿回执");
              r.state="done";r.clicked=true;r.receipt=actual;delete r.reason;delete r.next;break;
            }catch(e){
              const needs=e.handoff?.status==="needs_user";
              if(!needs||!interactive||Date.now()>=deadline)throw e;
              state.status="login";r.state="needs_login";r.reason=e.message;r.next="请在官网扫码";await checkpoint();
              // Keep the original QR challenge alive. Opening the composer again
              // while the phone is scanning can invalidate its code on some sites.
              const cfg=t.platform==="mp"?{hosts:["mp.weixin.qq.com"]}:config(t.platform);
              let waiting=true;
              while(waiting && Date.now()<deadline){
                await delay(2000);waiting=false;
                for(const tab of ctx.pages().filter(tab=>tab!==keeper)){
                  if(await challengeOn(tab,cfg).catch(()=>null)){waiting=true;break;}
                }
              }
              if(waiting)throw e;
              state.status="running";
              for(const tab of ctx.pages())if(tab!==keeper)await tab.close().catch(()=>{});
              if((await ledger()).some(v=>v.session===r.session))throw e;
            }
          }
        }catch(e){
          const record=(await ledger()).find(v=>v.session===r.session);
          r.clicked=Boolean(record && record.state!=="needs_user")||r.clicked===true;
          if(e.handoff?.status==="needs_user"){deferred.add(scope);r.state="needs_login";r.next="resume";}
          else {r.state=r.clicked?"uncertain":"failed";r.next=r.clicked?"query / resume 只续查":"修正后续接";}
          r.reason=message(e);
        }finally{
          if(ctx)for(const tab of ctx.pages())if(tab!==keeper)await tab.close().catch(()=>{});
          state.status="running";delete state.active;await checkpoint();
        }
      }
      await ctx?.close();ctx=null;
      const entries=Object.values(state.items);
      state.status=entries.some(r=>r.state==="needs_login")?"paused":entries.every(r=>r.state==="done")?"done":"partial";
    }catch(e){state.status="failed";state.reason=message(e);}
    finally{
      try{await ctx?.close();}finally{
        clearInterval(timer);await pulse;delete state.active;
        await checkpoint();await save(ownerFile,{...owner,heartbeat:Date.now(),released:true});
      }
    }
  });}catch(e){
    if(e.code!=="BUSY"){
      await writeOnce(stateFile,{status:"failed",reason:message(e),items:{}});
      await save(notice,{error:message(e)});return;
    }
    const owner=await read(ownerFile);
    const same=!owner?.released&&await alive(owner);
    if(!same)await writeOnce(stateFile,{status:"busy",reason:e.message,items:{}});
    await save(notice,{busy:true,same,message:e.message});
  }
}
export async function command(cmd,args){
  await mkdir(home,{recursive:true,mode:0o700});
  if(cmd==="pref")return pref(args);
  if(cmd==="query")return (await import("./query.js")).query(args);
  if(cmd==="batch-worker")return work(...args);
  const options=[...args],at=options.indexOf("--wait");
  let seconds=55;
  if(at!==-1){
    const word=options[at+1];seconds=Number(word);
    if(!/^\d+$/.test(word||"")||seconds>60)throw Error("--wait 接受 0 至 60 秒");
    options.splice(at,2);
  }
  let [op,arg]=options;
  if(op==="--status"||op==="--resume"){
    if(options.length!==2)throw Error("请给出批次号");
    const current=await status(arg);
    if(op==="--status"||current.status==="done")return waitStatus(arg,seconds);
    const owner=await read(path.join(batchDir(arg),"owner.json"));
    if(!owner?.released && await alive(owner))return waitStatus(arg,seconds);
    return start(arg,batchDir(arg),"resume",seconds);
  }
  if(options.length!==1 || !op || op.startsWith("-"))throw Error("run 任务.json | run --status 批次 | run --resume 批次");
  const input=JSON.parse(await readFile(op,"utf8")),id=digest(input).slice(0,24),dir=batchDir(id);
  await mkdir(dir,{recursive:true,mode:0o700});
  const created=await writeOnce(path.join(dir,"input.json"),input);
  const snapshotFile=path.join(dir,"preferences.json");
  if(!await read(snapshotFile))await writeOnce(snapshotFile,await preferenceSnapshot(input));
  const {effective}=await read(snapshotFile);
  if(effective.length)process.stderr.write("本批实际采用的本机偏好 "+JSON.stringify(effective)+"\n");
  if(!created){
    const current=await status(id);
    if(current.resumeCommand)return current;
  }
  return start(id,dir,"new",seconds);
}
