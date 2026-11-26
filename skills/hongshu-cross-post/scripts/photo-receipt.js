import path from "node:path";
import {config,receiptDate,titleCards} from "./platforms.js";
import {capture} from "./evidence.js";
import {actualTitle,verifyCopy,checkImages} from "./photo-form.js";
import {fitPhotoPage,mpHome} from "./photo-entry.js";
import {digest} from "./material.js";
import {requestHuman} from "./runtime.js";

export async function openList(p,t,refresh=false){
 const k=t.platform,broadcast=k==="mp"&&t.action==="broadcast";
 await fitPhotoPage(p,k);
 if(refresh){try{await p.reload({waitUntil:"domcontentloaded"});}catch(e){if(!e.message.includes("ERR_ABORTED"))throw e;await p.waitForLoadState("domcontentloaded");}}
 else if(k==="mp"){
   await p.goto(mpHome,{waitUntil:"domcontentloaded"});
   const entry=p.getByText(broadcast?"发表记录":"草稿箱",{exact:true}).filter({visible:true});
   const section=p.getByText("内容管理",{exact:true}).filter({visible:true});
   await entry.or(section).first().waitFor();
   if(!await entry.count())await section.first().click();
   await entry.first().click();
 }else await p.goto(config(k).list,{waitUntil:"domcontentloaded"});
 if(broadcast){await p.locator(".publish_record_history").waitFor();await p.locator(".weui-desktop-mass__content").or(p.getByText(/暂无发表记录|暂无数据/)).first().waitFor();return;}
 const ready=k==="mp"?p.locator('.weui-desktop-draft__toolbar').or(p.getByText("暂无素材",{exact:true})):p.locator(config(k).listCard).or(p.getByText(/^(暂无作品|暂无笔记|暂无相关作品|没有找到相关笔记)$/));
 await ready.first().waitFor({timeout:15000});
 if(k==="mp"){
   const tab=p.locator(".header_button:not(.currentTab) button").filter({hasText:/^\s*贴图/}).first();
   if(await tab.count()){await tab.click();await p.locator(".header_button.currentTab").filter({hasText:/^\s*贴图/}).waitFor({timeout:8000});await p.waitForTimeout(600);}
   await p.locator(".weui-desktop-card[data-appid]").or(p.getByText("暂无素材",{exact:true})).first().waitFor();
 }
}
export function matching(p,t,m){
 const label=actualTitle(t,m)||m.body.split("\n")[0].slice(0,18);
 if(t.platform==="mp"&&t.action==="broadcast")return p.locator(".publish_record_history .weui-desktop-mass__content").filter({has:p.getByText(label,{exact:true})});
 if(t.platform!=="mp")return titleCards(p,t.platform,label);
 return p.locator(".weui-desktop-card[data-appid]").getByText(label,{exact:true}).filter({visible:true});
}
export async function rowKey(row,k,action){
 if(k==="mp"&&action==="draft"){
   const id=await (await draftCard(row)).getAttribute("data-appid");
   if(!/^\d+$/.test(id||""))throw Error("草稿卡片缺少可核对的稿件编号");
   return id;
 }
 const text=await row.innerText();
 if(k==="mp"){
   const link=row.locator("a.weui-desktop-mass-appmsg__title");
   if(await link.count()){
     const href=await link.first().getAttribute("href");
     if(href&&/^https?:\/\//.test(href))return digest([href]);
   }
   return digest([text.replace(/\s+/g," ").trim()]);
 }
 const time=text.match(receiptDate)?.[0];
 if(!time)throw Error("作品行未读到提交时间");
 return digest([time,await row.evaluate(e=>{const img=e.querySelector("img.content,img");return img?.currentSrc?new URL(img.currentSrc).pathname:"";})]);
}
export async function keys(p,t,m){
 const out=[];for(const row of await matching(p,t,m).all())out.push(await rowKey(row,t.platform,t.action));return out;
}
const mpQuotaRe=/(?:群发|通知)次数.{0,4}(?:已用完|不足|为\s*0)|已无.{0,6}(?:群发|通知)次数|已达今日.{0,6}上限|无法开启群发通知/;
const mpDialogSel='.weui-desktop-dialog:visible,[role=dialog]:visible';
const closeDialog=async d=>{const b=d.getByRole("button",{name:/^(取消|关闭)$/}).filter({visible:true}).or(d.locator(".weui-desktop-dialog__close-btn:visible")).first();if(await b.count())await b.click();await d.waitFor({state:"hidden",timeout:5000}).catch(()=>{});};

export async function submitButton(p,t,reserve){
 const k=t.platform;
 if(new URL(p.url()).origin!==new URL(k==="mp"?mpHome:config(k).edit).origin)throw Error("编辑页站点已变化");
 const findBtn=async label=>{
   let b=k==="xhs"?p.locator("xhs-publish-btn:visible"):p.getByRole("button",{name:label,exact:true}).filter({visible:true});
   if(!await b.count()&&k==="mp")b=p.getByText(label,{exact:true}).filter({visible:true});
   if(await b.count()!==1||!await b.isEnabled())throw Error("提交入口尚未就绪："+label);
   return b;
 };
 const btn=await findBtn(k==="mp"?(t.action==="draft"?"保存为草稿":"发表"):"发布");
 let pos;
 if(k==="xhs"){
   if(await btn.getAttribute("submit-text")!=="发布"||await btn.getAttribute("submit-disabled")!=="false")throw Error("小红书发布栏尚未就绪");
   const box=await btn.boundingBox();if(!box||box.width<415||box.height<47)throw Error("发布栏尺寸变化");
   pos={position:{x:411,y:45}};
 }
 if(k==="douyin"){
   await btn.scrollIntoViewIfNeeded();
   try{await btn.click({...pos,trial:true,timeout:10000});}
   catch(e){const reason=e.message.split("\n").find(l=>/intercepts pointer events|not visible|not enabled|detached/i.test(l));throw Error("未点击提交，编辑页按钮不可用："+(reason?.trim().slice(0,180)||"请检查遮挡或官网提示"));}
 }
 if(k!=="mp"){await reserve(t.action);await btn.click(pos);return {action:t.action};}
 const waitIdle=async()=>p.getByText(/自动保存中/).filter({visible:true}).first().waitFor({state:"hidden",timeout:12000}).catch(()=>{});
 if(t.action==="draft"){
   await waitIdle();await reserve("draft");
   for(let i=0;i<2;i++){
     await btn.click();
     if(await p.getByText("保存成功",{exact:true}).filter({visible:true}).first().waitFor({timeout:8000}).then(()=>true,()=>false))break;
     await waitIdle();
   }
   return {action:"draft"};
 }
 await waitIdle();
 const dialogs=p.locator(mpDialogSel).filter({hasText:/发表|群发|确认|次数|扫码|二维码/});
 for(let i=0;i<2;i++){
   await btn.click();
   if(await dialogs.first().waitFor({timeout:7000}).then(()=>true,()=>false))break;
   const err=await p.getByText(/校验失败|必须插入一张图片/).filter({visible:true}).first().innerText().catch(()=>"");
   if(err)throw Error("公众号发表前校验未通过："+err.trim());
   if(i)throw Error("未弹出发表确认框，请核对编辑页");
   await p.waitForTimeout(800);
 }
 const dialog=dialogs.first(), text=(await dialog.innerText()).trim();
 if(mpQuotaRe.test(text)){
   await closeDialog(dialog);
   const draftBtn=await findBtn("保存为草稿");
   await reserve("draft");await draftBtn.click();
   await p.waitForFunction(()=>new URLSearchParams(location.search).has("appmsgid"),null,{timeout:6000}).catch(()=>{});
   return {action:"draft",fallback:"今日群发额度已用完，已转存草稿",appmsgid:new URL(p.url()).searchParams.get("appmsgid")||null};
 }
 if(!/无需开启群发通知/.test(text)){
   if(/群发对象|发送对象/.test(text)&&!/全部(?:用户|粉丝)|所有(?:用户|粉丝)/.test(text))throw Error("请核对群发受众，此页保留");
   const toggle=dialog.getByRole("checkbox",{name:/群发通知/});
   if(await toggle.count()===1&&await toggle.isEnabled()&&!await toggle.isChecked())await toggle.check();
 }
 if(await dialog.locator('.mass-send__timer-wrp input[type="checkbox"]:checked').count())throw Error("弹窗误开了定时发表，已停止提交");
 const okRe=/^(发表|确认发表|群发|确认群发|立即群发)$/;
 let ok=dialog.locator("button.weui-desktop-btn_primary:visible").filter({hasText:okRe});
 if(!await ok.count())ok=dialog.getByRole("button",{name:okRe}).filter({visible:true});
 if(await ok.count()!==1||!await ok.isEnabled()){
   if(/扫码|二维码/.test(text))return {needsQr:true,message:"公众号发表需要本人微信扫码确认"};
   throw Error("发表确认按钮不可用，请核对官网弹窗");
 }
 await reserve("broadcast");await ok.click();
 const qr=p.locator(mpDialogSel).filter({hasText:/扫码|二维码/}).first();
 if(await qr.waitFor({timeout:2500}).then(()=>true,()=>false)){
   const msg="公众号发表需要本人微信扫码确认";
   try{await requestHuman(p,msg);}
   catch(e){if(e.handoff?.status==="needs_user"){await closeDialog(qr);return {needsQr:true,message:msg};}throw e;}
   await qr.waitFor({state:"hidden",timeout:600000});
 }
 return {action:"broadcast"};
}
export async function newRow(p,t,m,record){
 const end=Date.now()+40000;
 do{
   await openList(p,t,true);
   const diff=[];
   for(const r of await matching(p,t,m).all())if(!record.baseline.includes(await rowKey(r,t.platform,t.action)))diff.push(r);
   if(diff.length>1)throw Error("出现多条同名新稿，保留现场核对");
   if(diff.length===1)return diff[0];
   await p.waitForTimeout(1200);
 }while(Date.now()<end);
 throw Error("列表仍未找到本批新稿，只续查回执");
}
export async function socialReceipt(p,t,row,dir,id){
 const text=await row.innerText(),time=text.match(receiptDate)?.[0];
 if(!time)throw Error("回执行缺发布时间");
 const status=text.match(/审核中|已发布|未通过|审核失败|已发表/)?.[0]||"作品管理已收录";
 return {key:await rowKey(row,t.platform),time,status,desktop:[await capture(p,row,path.join(dir,id+"-"+t.platform+"-receipt.png"))]};
}
export async function mpReceipt(p,t,m,row,dir,id){
 const card=await draftCard(row);
 const proof=await capture(p,card,path.join(dir,id+"-mp-draft.png"));
 const pending=p.context().waitForEvent("page",{timeout:5000}).catch(()=>null);
 await card.hover();
 const action=card.locator(".weui-desktop-card__bd .weui-desktop-tooltip__wrp.weui-desktop-link > a.weui-desktop-icon-btn:visible");
 if(await action.count()!==1)throw Error("未找到该草稿唯一编辑入口");
 await action.click();const edit=(await pending)||p;
 try{
   await edit.locator(".share-text__input .ProseMirror").waitFor({timeout:12000});
   await verifyCopy(edit,t,m);const imageCheck=await checkImages(edit,"mp",m);
   const assetId=new URL(edit.url()).searchParams.get("appmsgid");
   if(!assetId||!/^\d+$/.test(assetId)||assetId!==await card.getAttribute("data-appid"))throw Error("重开草稿未读到唯一稿件编号");
   const area=edit.locator(".image-selector__bottom-list-item").first().locator('xpath=ancestor::*[.//*[contains(@class,"share-text__input")]][1]');
   const rect=await area.boundingBox();
   if(rect&&rect.height<5600){const width=await edit.evaluate(()=>innerWidth);await edit.setViewportSize({width,height:Math.ceil(rect.height)+450});await area.scrollIntoViewIfNeeded();}
   const editorProof=await capture(edit,area,path.join(dir,id+"-mp-reopened.png"));
   return {key:assetId,status:"草稿箱已重开核对",imageCheck,desktop:[proof,editorProof]};
 }finally{if(edit!==p)await edit.close();else await openList(p,t);}
}
export async function draftCard(title){
 const card=title.locator('xpath=ancestor::*[@data-appid and contains(@class,"weui-desktop-card")][1]');
 if(await card.count()!==1)throw Error("尚未识别这条草稿卡片");
 return card;
}
