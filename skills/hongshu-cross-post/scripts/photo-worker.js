import path from "node:path";
import {mkdir,readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import {home,backgroundTab} from "./runtime.js";
import {save,read,availableSubmission,reserveSubmission} from "./control.js";
import {photoEntry,photoIdentity} from "./photo-entry.js";
import {actualTitle,preparePhoto,verifyCopy,checkImages} from "./photo-form.js";
import {openList,keys,matching,rowKey,newRow,submitButton,socialReceipt,mpReceipt,draftCard} from "./photo-receipt.js";
import {digest} from "./material.js";
import {capture} from "./evidence.js";
export async function verifyPhotoHome(ctx,t,s){
  const saved=await read(path.join(home,"accounts",t.platform+".json"));
  if(!s.home || s.home.isClosed())s.home=await backgroundTab(ctx);
  const value=await photoIdentity(s.home,t.platform,t.account?.value||saved?.display);
  if(saved?.display!==value){
    const dir=path.join(home,"accounts");await mkdir(dir,{recursive:true,mode:0o700});
    await save(path.join(dir,t.platform+".json"),{display:value});
  }
  return value;
}

export async function runPhotoTarget({ctx,id,job,out},s,cmd){
   const {key,t,assets:m,approval}=s,k=t.platform;
   s.list??=await backgroundTab(ctx);
   const marker=path.join(home,"submissions",digest(["photo",k,s.identity,m.signature])+".json");
   let record=await read(marker);
   const eligible=r=>availableSubmission(r,id);
   if(cmd.op==="prepare"){
     if(!eligible(record))throw Error("该素材已有提交记录，先查原回执");
     if(s.edit)await s.edit.close();s.prepared=null;
     await openList(s.list,t);s.baseline=await keys(s.list,t,m);
     s.edit=await photoEntry(ctx,k,s.identity,s.home);s.home=null;
     const images=await preparePhoto(s.edit,t,m);
     s.images=images;s.previous=record;s.prepared=digest([approval,key,images]);return {prepared:s.prepared,account:s.identity,title:actualTitle(t,m),images};
   }
   if(cmd.op==="clean"){
     if(!job.testBatch||!job.receiptDir||cmd.approval!==approval||record?.approval!==approval||!["receipt","removing","removed"].includes(record?.state))throw Error("清理范围或回执未核准");
     if(record.state==="removed")return {removed:true};
     if(JSON.stringify(record.desktop.map(d=>d.sha256))!==JSON.stringify(cmd.seen?.[key]))throw Error("请先打开并核对本稿回执");
     for(const shot of record.desktop)if(createHash("sha256").update(await readFile(shot.file)).digest("hex")!==shot.sha256)throw Error("回执图内容变化");
     await openList(s.list,t);const matched=matching(s.list,t,m);
     const findTarget=async()=>{
       const hits=[];
       for(const r of await matched.all()){
         if(k!=="mp"){if(await rowKey(r,k)===record.key)hits.push(r);}
         else{const c=await draftCard(r);if(await c.getAttribute("data-appid")===record.key)hits.push(r);}
       }if(hits.length>1)throw Error("同稿匹配不唯一");return hits[0];
     };
     const row=await findTarget();
     if(record.state==="receipt"){
       if(!row)throw Error("回执所对应稿件不在当前列表");
       const card=k==="mp"?await draftCard(row):row;
       await card.hover();
       const trigger=k==="douyin"?card.getByText("删除作品",{exact:true}):k==="xhs"?card.locator(".note-card__action-btn--del"):card.locator('.weui-desktop-card__bd .weui-desktop-tooltip__wrp:not(.weui-desktop-link) > a.weui-desktop-icon20:visible');
       if(await trigger.count()!==1||!await trigger.isVisible())throw Error("本稿卡片内未找到唯一删除入口");
       record={...record,state:"removing"};await save(marker,record);await trigger.click();
     }
     const dlg=s.list.locator('[role=dialog]:visible,dialog:visible,.d-modal:visible,.weui-desktop-dialog:visible,[class*="modal-content"]:visible').filter({hasText:/删除|移除/});
     const ok=k==="mp"&&row?(await draftCard(row)).getByRole("button",{name:"删除",exact:true}).filter({visible:true}):dlg.getByText(/^(确定|删除|确认删除|确定删除|确认)$/,{exact:true}).filter({visible:true});
     if(await ok.first().waitFor({timeout:2500}).then(()=>true,()=>false)){if(await ok.count()!==1)throw Error("删除确认项不唯一");await ok.click();}
     await s.list.waitForTimeout(650);await openList(s.list,t,true);
     await s.list.waitForTimeout(350);
     if(await findTarget())throw Error("刷新后同稿仍在，保留删除状态");
     if(k==="mp"&&t.action==="draft"&&record.baseline?.length){
       const remaining=await keys(s.list,t,m);
       if(!record.baseline.every(key=>remaining.includes(key)))throw Error("本次草稿已移除，列表未能完整回读原有同名稿，请核对草稿箱");
     }
     await save(marker,{...record,state:"removed"});return {removed:true};
   }
   if(cmd.op==="submit"){
     if(!s.prepared||cmd.approval!==approval||cmd.seen?.[key]!==s.prepared||!eligible(record))throw Error("成稿核对值不匹配或已经尝试提交");
     await verifyCopy(s.edit,t,m,s.images);await checkImages(s.edit,k,m);
     const out0=await submitButton(s.edit,t,async(act=t.action)=>{
       record={state:"uncertain",platform:k,action:act,account:s.identity,title:actualTitle(t,m),media:"photo",session:id,approval,testBatch:job.testBatch,started:Date.now(),baseline:act===t.action?s.baseline:[],...(s.images?.skipped?{note:s.images.skipped}:{})};
       await reserveSubmission(marker,id,s.previous,record);
     });
     if(out0?.needsQr){
       if(record?.session===id){record={...record,state:"needs_user"};await save(marker,record);}
       const e=Error(out0.message);e.handoff={status:"needs_user",message:out0.message,requiresVisibleLogin:true,pageKept:false};throw e;
     }
     if(out0?.fallback){record={...record,fallback:out0.fallback,fallbackAppmsgid:out0.appmsgid};await save(marker,record);}
     await s.edit.waitForTimeout(1200);
   }else if(cmd.op!=="recover")throw Error("未知图文动作");
   if(!record||record.approval!==approval)throw Error("没有本批提交记录");
   if(record.state!=="uncertain" && !(cmd.op==="recover"&&record.state==="receipt"&&cmd.refreshProof===true))return record;
   const action=record.action||t.action, target={...t,action};
   await openList(s.list,target);
   const fb=k==="mp"&&action==="draft"&&record.fallbackAppmsgid?s.list.locator(`.weui-desktop-card[data-appid="${record.fallbackAppmsgid}"]`):null;
   const row=fb&&await fb.waitFor({timeout:15000}).then(()=>true,()=>false)?fb.getByText(actualTitle(t,m),{exact:true}).filter({visible:true}).first():await newRow(s.list,target,m,record);
   let proof;
   if(k==="mp"&&action==="draft"){
     proof=await mpReceipt(s.list,target,m,row,out,id);
     if(record.fallback)proof.status=record.fallback+"（已重开核对）";
   }else if(k==="mp"){
     const status=(await row.innerText()).match(/已发表|已群发|群发成功|已发送群发通知/)?.[0];
     if(!status)throw Error("发表记录中尚未核实已发表，只可续查");
     proof={key:await rowKey(row,k,action),status,desktop:[await capture(s.list,row,path.join(out,id+"-mp-broadcast.png"))]};
   }else proof=await socialReceipt(s.list,target,row,out,id);
   if(record.state==="receipt"&&record.key!==proof.key)throw Error("新回执的作品编号与已有记录不同");
   record={...record,...proof,state:"receipt"};await save(marker,record);return proof;
}
