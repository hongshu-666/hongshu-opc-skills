import {accountVerifier} from "./account.js";
import path from "node:path";
import {copyFile,constants} from "node:fs/promises";
import {home,backgroundTab} from "./runtime.js";
import {save,read,availableSubmission,reserveSubmission} from "./control.js";
import {digest} from "./material.js";
import {config} from "./platforms.js";
import {videoEntry,prepare,clickSubmit,baseline,receipt} from "./workflow.js";
import {desktopProof,cleanup} from "./cleanup.js";

export async function runVideo({ctx,id,job,dir},s,cmd){
  const {t,assets}=s,k=t.platform;
  const markerFor=t=>path.join(home,"submissions",digest([t.platform,t.account.selfPath||t.account.value,assets.video.sha256])+".json");
  const marker=markerFor(t),approval=s.approval;
  s.edit??=await backgroundTab(ctx);
  s.list??=await backgroundTab(ctx);
  if(cmd.op==="prepare"){
    const previous=await read(marker);
    if(!availableSubmission(previous,id))throw Error("已有提交记录；请先查回执");
    s.prepared=null;
    const old=await baseline(s.list,t);
    if(k==="channels"){
      s.edit=await videoEntry(ctx,s.edit,k);
    }
    const ready=await prepare(s.edit,t,assets,dir,{opened:k==="channels"});
    s.previous=previous;s.old=old;s.prepared=ready;return ready;
  }
  let record=await read(marker);
  if(cmd.op==="submit"||cmd.op==="recover"){
    if(cmd.op==="submit"&&(!s.prepared||cmd.approval!==approval||cmd.seen?.[k]!==s.prepared.proof.sha256))
      throw Error("请按本批发布清单核对封面并传入成稿散列");
    if(cmd.op==="submit" && (!record||record.state==="removed")){
      if(s.edit.url()!==s.prepared.url)throw Error("编辑页面已切换");
      const pending={state:"uncertain",session:id,approval,platform:k,title:t.title,account:t.account.value,testBatch:job.testBatch,utc:new Date().toISOString(),baseline:s.old};
      s.signal=await clickSubmit(s.edit,t,()=>reserveSubmission(marker,id,s.previous,pending));
      record=pending;
    }
    if(!record||record.approval!==approval||record.state==="removed")throw Error("没有本批待核提交");
    if(record.state==="receipt")return record;
    if(s.list.url()==="about:blank")await s.list.goto(config(k).list,{waitUntil:"domcontentloaded"});
    let row;try{row=await receipt(s.list,t,record,dir,job.durationSeconds);}catch(e){return {state:"uncertain",signal:s.signal,error:e.message};}
    const outDir=job.cleanup?.receiptDir||dir,shots=[row.image,...(row.player?[row.player.image]:[])];
    const files=[];
    for(const [i,shot] of shots.entries()){
      const name=path.join(outDir,id+"-"+k+(i?"-player":"-receipt")+".png");
      await copyFile(shot.file,name,constants.COPYFILE_EXCL).catch(e=>{if(e.code!=="EEXIST")throw e;});files.push(name);
    }
    const desktop=await desktopProof(outDir,files,shots);
    record={...record,...row,state:"receipt",desktop};await save(marker,record);return {status:row.status,time:row.time,duration:row.duration,desktop,signal:s.signal};
  }
  if(cmd.op==="clean"){
    if(!job.cleanup||cmd.approval!==approval)throw Error("本批未授权清理");
    const evidenceTargets=job.cleanup.perPlatform===true && job.cleanup.afterAllReceipts!==true?[t]:job.targets;
    for(const u of evidenceTargets){const r=await read(markerFor(u));if(!r?.desktop?.length||JSON.stringify(cmd.seen?.[u.platform])!==JSON.stringify(r.desktop.map(d=>d.sha256)))throw Error("请先逐张打开并核清待清理范围的桌面回执");}
    if(record?.state==="removed")return {removed:true};
    const cfg=config(k),page=s.list;await page.goto(cfg.list,{waitUntil:"domcontentloaded"});
    const selector=cfg.listCard;
    const acts=(op,more)=>cleanup({page,cfg,t,a:{op,approval,...more},job,markerFor,approval,verify:(k,a)=>accountVerifier(ctx).verify(config(k),a)});
    if(record.state==="receipt")await acts("remove",{row:{css:selector+':has-text('+JSON.stringify(t.title)+'):has-text('+JSON.stringify(record.time)+')'}});
    const d='[role=dialog]:visible,.d-modal:visible,.weui-desktop-dialog:visible,.bcc-dialog:visible,.semi-modal:visible,[class*=modal-content]:visible';
    const modal=page.locator(d).filter({hasText:/删除|移除/}).filter({has:page.getByRole("button",{name:/^(?:删除|确定|确认|确认删除|确定删除)$/})}).last();
    if(await modal.waitFor({timeout:2500}).then(()=>true,()=>false)) await acts("confirmRemove",{dialogNode:modal});
    return acts("checkRemoved",{listReady:{css:selector+' >> nth=0'}});
  }
  throw Error("未知命令");
}
