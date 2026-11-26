import path from "node:path";
import {capture} from "./evidence.js";
import {config,titleCards} from "./platforms.js";
import {digest} from "./material.js";
import {accountVerifier} from "./account.js";
import {requestHuman} from "./runtime.js";
import {verifySchedule} from "./schedule.js";

const tabs={douyin:/^(全部作品|已发布|定时发布|定时作品)$/,xhs:/^(全部笔记|全部|定时发布|待发布)$/,bilibili:/^(全部稿件|进行中|已发布|审核中|待发布|未通过)(?:\s*\d+)?$/,channels:/^(全部|定时发表|待发表)$/};
function normalized(s){return s.normalize("NFKC").replace(/[年月/.]/g,"-").replace(/日/g,"").replace(/\s+/g," ").trim();}
function indicator(s){return s.match(/定时发布中|定时发表中|将于|预约发布|定时发布|定时发表|预定发布|待定时发布/)?.[0];}
async function waitList(p,t) {
  await p.locator(config(t.platform).listCard).or(p.getByText(/^(暂无作品|暂无笔记|暂无相关作品|暂无相关视频|暂无稿件|空空如也|暂无数据|还没有发表过内容)$/)).filter({visible:true}).first().waitFor({timeout:12000});
}
export async function listing(p,t) {
  await p.goto(config(t.platform).list,{waitUntil:"domcontentloaded"});
  await waitList(p,t);
}
function matches(p,t){return titleCards(p,t.platform,t.title).filter({visible:true});}
async function identity(r,t) {
  await r.scrollIntoViewIfNeeded();
  await r.locator("img").first().evaluate(el=>el.decode().catch(()=>{}),null,{timeout:3000}).catch(()=>{});
  const data=await r.evaluate(el=>{
    const href=Array.from(el.querySelectorAll('a[href]'),a=>a.getAttribute('href')||'').find(s=>/BV[a-zA-Z0-9]+|\/(?:explore|discovery\/item|video)\/[a-zA-Z0-9]+|[?&](?:noteId|note_id|item_id|aweme_id|objectId)=[\w-]+/.test(s));
    const asset=el.querySelector("img.content,img.thumb,img");
    const cover=el.querySelector('[class^="video-card-cover-"]');
    const background=cover && getComputedStyle(cover).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
    const src=asset?.currentSrc||background;
    return [el.getAttribute("data-id")||el.getAttribute("data-note-id")||"",href||"",src?new URL(src,location.href).pathname:"",background?new URL(background,location.href).pathname:""];
  });
  const id=data[0]||data[1].match(/(?:BV[a-zA-Z0-9]+|(?:item_id|aweme_id|objectId|note_id|noteId)=[\w-]+|(?:explore|discovery\/item|video)\/[\w-]+)/)?.[0];
  if(id)return {id,kind:"platform"};
  const cover=untitledPhoto(t)?data[3]:data[2];
  if(!cover)return null;
  // Older baselines could hash a decorative image layered over the actual cover.
  const legacyId=data[2] && data[2]!==cover ? digest([t.platform,t.title,data[2]]) : null;
  return {id:digest([t.platform,t.title,cover]),kind:"title-and-thumbnail",legacyId};
}
export async function beforeSubmission(p,t) {
  await listing(p,t);
  const items=[];
  for(const r of await matches(p,t).all()){
    const key=await identity(r,t);
    if(!key)throw Error("原有同名稿尚无可核对标识，暂缓提交");
    items.push(key.id);
  }
  return items;
}
function untitledPhoto(t){return t.platform==="douyin" && t.media==="photo" && !t.includeTitle;}

// Read only the status area. Dates and status words can also appear in the caption.
async function photoBooking(card) {
  const meta=card.locator('[class^="info-op-left-"]:visible');
  const states=await meta.locator('[class^="info-status-"]:visible').allInnerTexts();
  if(states.length!==1)return null;
  const status=states[0].trim();
  const dates=["审核中","已发布","已发表"].includes(status)
    ? meta.getByText(/^\s*\d{4}年\d{1,2}月\d{1,2}日\s*\d{2}:\d{2}\s*$/)
    : meta.locator('[class^="schedule-time-"]');
  const times=await dates.filter({visible:true}).allInnerTexts();
  if(times.length!==1)return null;
  const parts=normalized(times[0]).match(/^(?:定时\s*:\s*)?(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{2}:\d{2})(?::00)?$/);
  if(!parts)return null;
  const [,year,month,day,time]=parts;
  return {status,minute:`${year}-${month.padStart(2,"0")}-${day.padStart(2,"0")} ${time}`};
}
export async function locate(p,t,record,requireKey=false,history=false) {
  const hits=[];
  for(const r of await matches(p,t).all()){
    const untitled=untitledPhoto(t);
    if(untitled){
      const captions=await r.locator('[class^="info-title-text-"]:visible').allInnerTexts();
      if(captions.length!==1)throw Error("作品卡片未显示唯一的正文预览");
      if(!captions[0].trimStart().startsWith(t.title))continue;
    }else if(t.platform==="xhs"){
      const titles=await r.locator(".note-card__title:visible").allInnerTexts();
      if(titles.length!==1 || titles[0].trim()!==t.title)continue;
    }else{
      const lines=(await r.innerText()).split("\n").map(s=>s.trim());
      if(!lines.some(line=>line===t.title||line.startsWith(t.title+" #")||line.startsWith(t.title+"#")||t.platform==="douyin"&&line.startsWith(t.title+"。"+(t.captionPrefix||""))))continue;
    }
    const key=await identity(r,t);
    if(!key && (requireKey||untitled))throw Error("同题作品的封面标识仍未加载，不能判作已清理");
    if(!key || record.baseline.includes(key.id) || (key.legacyId && record.baseline.includes(key.legacyId)))continue;
    if(record.key && record.key!==key.id && record.key!==key.legacyId)continue;
    let booking;
    if(untitled){
      booking=await photoBooking(r);
      if(!booking)throw Error("同前缀新稿的状态或预约分钟不明确");
      if(booking.minute!==t.scheduleAt){
        if(record.key)throw Error("原稿的预约时间已变化");
        continue;
      }
      const pendingReview=booking.status==="审核中" && Date.parse(t.scheduleAt.replace(" ","T")+":00+08:00")>Date.now();
      if(!/^(定时发布中|定时发布|待定时发布|预约发布)$/.test(booking.status) && !pendingReview && !(history && /^(已发布|已发表)$/.test(booking.status)))throw Error("同一时刻的作品未显示预约或待审状态");
    }
    if(t.platform==="xhs"){
      const row=r.locator(".note-card__row--time:visible");
      const states=await row.locator(".note-card__schedule:visible").allInnerTexts();
      const times=await row.locator(".note-card__time:visible").allInnerTexts();
      if(states.length===1 && states[0].trim()==="定时发布" && times.length===1 && normalized(times[0])===t.scheduleAt)
        booking={status:"定时发布",minute:t.scheduleAt};
    }
    hits.push({r,key,booking});
  }
  if(hits.length>1)throw Error("有多条同题新稿，保留记录核对，不执行删除");
  return hits[0];
}
export async function searchNew(p,t,record,{once=false,history=false,waitForBooking=false}={}) {
  const end=Date.now()+(once?0:45000);
  do{
    await listing(p,t);
    let found=await locate(p,t,record,once,history);
    if(!found){
      const strip=p.locator('[role=tab],.secondTabs a.txt-item,[class*=tab-item i],[class*=tabItem],[class*=tab-label i]').filter({visible:true,hasText:tabs[t.platform]});
      for(const node of await strip.all()){
        if(!await node.isVisible())continue;await node.click();await p.waitForTimeout(350);
        found=await locate(p,t,record,once,history);if(found)break;
      }
    }
    if(found){
      if(!waitForBooking || found.booking)return found;
      // Follow this new note while review gives way to its scheduled minute.
      record={...record,key:found.key.id};
    }
    if(once)break;
    await p.waitForTimeout(waitForBooking ? 1500 : 800);
  }while(Date.now()<end);
  return waitForBooking ? locate(p,t,record) : null;
}
export async function bookedReceipt(p,t,record,dir,name,{history=false}={}) {
  if(untitledPhoto(t)){
    try {
      await accountVerifier(p.context()).verify(config(t.platform),t.account);
      const hit=await searchNew(p,t,record,{history});
      if(!hit)throw Error("当前列表尚无可核实的同稿");
      const desktop=[await capture(p,hit.r,path.join(dir,name+"-列表.png"))];
      return {key:hit.key.id,keyType:hit.key.kind,title:t.title,desktop,status:hit.booking.status,scheduledAt:hit.booking.minute,verified:true};
    }catch(e){
      if(e.handoff){e.handoff={...e.handoff,submissionStatus:"已点击，待核实",next:"recover"};throw e;}
      return {status:"已点击，待核实",reason:e.message.split("Call log")[0].trim(),verified:false,next:"recover"};
    }
  }
  const found=await searchNew(p,t,record,{waitForBooking:t.platform==="xhs"});
  if(!found)throw Error("后台未找到本次预约，只能续查");
  const {r,key}=found, text=await r.innerText(), status=indicator(text);
  const desktop=[await capture(p,r,path.join(dir,name+"-列表.png"))];
  const output={key:key.id,keyType:key.kind,title:t.title,desktop,status,verified:false};
  if(t.platform==="xhs"){
    if(found.booking)return {...output,status:found.booking.status,scheduledAt:found.booking.minute,verified:true};
    return {...output,reason:"同稿已出现，后台尚未核实目标预约分钟",next:"recover"};
  }
  const displayed=normalized(text);
  const wanted=t.scheduleAt;
  const rx=new RegExp("(?<!\\d)"+wanted.replace(/-0(\d)/g,"-0?$1").replace(" ","\\s*")+"(?::00)?(?!\\d)");
  let readback=status && rx.test(displayed) ? status : null;
  if(!readback && t.platform==="douyin" && t.media==="photo" && Date.parse(wanted.replace(" ","T")+":00+08:00")>Date.now()){
    const times=r.getByText(/^\s*\d{4}年\d{1,2}月\d{1,2}日\s*\d{2}:\d{2}\s*$/).filter({visible:true});
    const review=r.getByText("审核中",{exact:true}).filter({visible:true});
    if(await review.count()===1 && await times.count()===1 && rx.test(normalized(await times.innerText())))readback="审核中";
  }
  if(readback)return {...output,status:readback,verified:true,scheduledAt:wanted};
  const edit=r.getByText(/^(编辑|修改定时|修改时间|编辑作品)$/,{exact:true}).filter({visible:true});
  if(await edit.count()!==1)return output;
  // Read the saved scheduling controls of this exact backend record.
  const opened=p.context().waitForEvent("page",{timeout:2500}).catch(()=>null);
  await edit.click();const tab=(await opened)||p;
  try {
    await tab.waitForLoadState("domcontentloaded");
    if(t.platform==="bilibili"){
      const title=tab.getByPlaceholder("请输入稿件标题");await title.waitFor({timeout:10000});
      if(await title.inputValue()!==t.title)return output;
      await tab.locator(".time-container .date-picker-timer:visible").waitFor({timeout:6000});
    }
    if(new URL(tab.url()).origin!==new URL(config(t.platform).edit).origin)return output;
    const time=await verifySchedule(tab,t,{existing:true});
    const area=tab.locator({douyin:'[class^=schedule-part-]',xhs:'.post-time-wrapper',bilibili:'.time-container:has-text("定时发布")',channels:'.post-time-wrap'}[t.platform]).filter({visible:true});
    desktop.push(await capture(tab,area,path.join(dir,name+"-预约详情.png")));
    return {...output,status:status||"后台重开定时设置",scheduledAt:time,verified:true};
  }catch{return output;}
  finally{if(tab!==p)await tab.close();else await listing(p,t);}
}
export async function removeBooking(p,t,record,{waiting=false}={}) {
  const validation=p.locator(".ui-modal:visible").filter({hasText:"验证并删除此视频"});
  async function handoff(){
    const message="请在B站当前「验证并删除此视频」窗口完成本人验证，完成后续查本稿。";
    await requestHuman(p,message);
    const e=Error(message);e.handoff={status:"needs_user",message,pageKept:true};throw e;
  }
  if(waiting && await validation.isVisible())return handoff();
  const hit=await searchNew(p,t,record,{once:true});
  if(!hit){if(record.state==="removing")return {removed:true};throw Error("本次回执对应的预约未找到");}
  const r=hit.r;await r.hover();
  if(t.platform==="bilibili"&&await r.locator(".more-btn").count()===1)await r.locator(".more-btn").hover();
  const selected={xhs:'.note-card__action-btn--del',bilibili:'.del-btn,.delete-btn,[title="删除"],[aria-label="删除"]',channels:'[title="删除"],[aria-label="删除"]'}[t.platform];
  let trigger=r.getByText(/^(删除稿件|删除作品|删除|撤回定时发布|取消定时发表)$/,{exact:true}).filter({visible:true});
  if(t.platform==="channels" && await r.getByText("删除",{exact:true}).count()===1)trigger=r.getByText("删除",{exact:true}).locator("..").locator(".opr-item");
  if(!await trigger.count() && selected)trigger=r.locator(selected).filter({visible:true});
  if(await trigger.count()!==1){
    const more=r.getByText(/^(更多|更多操作)$/,{exact:true}).or(r.locator('[title="更多"],[aria-label="更多"],.more-btn,.more-action,.more-wrap')).filter({visible:true});
    if(await more.count()===1){await more.click();trigger=r.getByText(/^(删除|删除作品)$/,{exact:true}).filter({visible:true});}
  }
  if(await trigger.count()!==1)throw Error("该预约稿卡片内尚未定位到唯一清理按钮");
  await trigger.click();
  if(t.platform==="bilibili" && await validation.waitFor({timeout:1500}).then(()=>true,()=>false))return handoff();
  const modal=p.locator('[role=dialog]:visible,dialog:visible,.d-modal:visible,.bcc-dialog:visible,.weui-desktop-dialog:visible,[class*=modal-content]:visible').filter({hasText:/删除|移除|撤回/});
  const ok=modal.getByText(/^(确定删除|确认删除|删除|确定|确认)$/,{exact:true}).filter({visible:true});
  if(await ok.first().waitFor({timeout:2000}).then(()=>true,()=>false)){if(await ok.count()!==1)throw Error("清理确认项不唯一");await ok.click();}
  await p.waitForTimeout(600);
  if(await searchNew(p,t,record,{once:true}))throw Error("刷新后仍找到同一条预约稿");
  return {removed:true};
}
