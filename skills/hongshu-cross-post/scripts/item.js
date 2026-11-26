import path from "node:path";
import {mkdir} from "node:fs/promises";
import {home,root,launch} from "./runtime.js";
import {openForAccounts,accountVerifier} from "./account.js";
import {serve} from "./control.js";
import {config} from "./platforms.js";
import {compileJob,assetHash,readAssets} from "./plan.js";
import {runVideo} from "./video-worker.js";
import {runPhotoTarget,verifyPhotoHome} from "./photo-worker.js";
import {bookingTime,runScheduled} from "./schedule.js";

export async function executeJob(id,job,shared) {
  const {tasks,approval}=shared?.execution??await compileJob(job,shared?.assets,{recover:shared?.recover});
  const scheduled=job.mode==="scheduled",first=tasks[0];
  if(shared && tasks.length!==1)throw Error("批次执行需唯一单项目标");
  if(shared?.assets)first.assets=shared.assets;
  if(job.mode==="single-now")job.targets=tasks.map(s=>s.t);
  const dir=path.join(root,"runs",id),out=job.receiptDir||dir;
  if(!path.isAbsolute(out))throw Error("回执目录需要绝对路径");
  await Promise.all([dir,path.join(home,"submissions")].map(d=>mkdir(d,{recursive:true,mode:0o700})));
  const session={id,job,dir,out,ctx:shared?.context,async reopenVisible(){
    await this.ctx.close();
    for(const s of tasks){s.home=null;s.edit=null;s.list=null;s.identity=null;s.prepared=null;s.awaitingOwner=false;}
    this.ctx=await launch({visible:true});
  }};
  async function identify(ctx,s){
    const {t}=s,k=t.platform;
    if(s.photo && (!scheduled || k==="mp"))return verifyPhotoHome(ctx,t,s);
    return accountVerifier(ctx).verify(config(k),t.account);
  }
  async function act(s,cmd,materialReads){
    const {t,photo,assets}=s;
    if(cmd.op==="prepare" || cmd.op==="recover" || !s.identity)s.identity=await identify(session.ctx,s);
    if(cmd.op==="prepare" && scheduled && t.platform!=="mp")bookingTime(t.scheduleAt,t.platform);
    if(cmd.op==="submit" || cmd.op==="prepare" && !shared){
      const source=scheduled?job.items[s.index]:job;
      // One mailbox command can address several platforms of the same article.
      const read=materialReads?.get(s.index)??readAssets({...source,type:photo?"photo":"video"});
      materialReads?.set(s.index,read);
      if(assetHash(await read)!==assetHash(assets))throw Error(cmd.op==="prepare"?"开工前素材或文案已变化":"上传后素材或文案已变化，停止提交");
      if(shared)await shared.beforeSubmit();
    }
    s.approval=approval;
    if(scheduled && t.platform!=="mp")return runScheduled(session,s,cmd);
    return photo?runPhotoTarget(session,s,cmd):runVideo(session,s,cmd);
  }
  if(shared){
    if(shared.recover)return act(first,{op:"recover"});
    const ready=await act(first,{op:"prepare"});
    const hash=ready.prepared||ready.proof?.sha256;
    if(!hash)throw Error("未能核实成稿");
    return act(first,{op:"submit",approval,seen:{[first.key]:hash}});
  }
  const byPlatform=new Map(tasks.map(s=>[s.t.platform,s]));
  const opened=await openForAccounts([...byPlatform.values()].map(s=>s.t),(c,t)=>identify(c,byPlatform.get(t.platform)));
  session.ctx=opened.context;
  const detail=scheduled?{items:tasks.map(s=>s.key)}:first.photo?
    {pages:first.assets.photos.length,title:first.assets.title}:{video:first.assets.video.name};
  try{return await serve(id,{approval,identities:opened.results,...detail},async cmd=>{
    if(cmd.op==="close")return {closed:true};
    const selected=tasks.filter(s=>cmd.platform==="all"||cmd.platform===s.key);
    if(!selected.length)throw Error("目标不在清单中，可用目标："+tasks.map(s=>s.key).join("、"));
    const materialReads=new Map();
    async function attempt(s){
      try{return [s.key,await act(s,cmd,materialReads)];}
      catch(e){return [s.key,e.handoff||{error:e.message.split("Call log")[0].slice(0,400)}];}
    }
    const entries=[];
    if(job.mode==="single-now"){
      const bili=cmd.op==="prepare" && selected.find(s=>s.key==="bilibili");
      if(bili)entries.push(await attempt(bili));
      entries.push(...await Promise.all(selected.filter(s=>s!==bili).map(attempt)));
    }else for(const s of selected)entries.push(await attempt(s));
    return Object.fromEntries(entries);
  });}finally{await session.ctx.close();}
}
