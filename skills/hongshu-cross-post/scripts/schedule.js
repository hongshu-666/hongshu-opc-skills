import path from "node:path";
import {mkdir} from "node:fs/promises";
import {home,backgroundTab} from "./runtime.js";
import {normalizeReceipt,read,save,availableSubmission,reserveSubmission} from "./control.js";
import {accountVerifier} from "./account.js";
import {config} from "./platforms.js";
import {digest,hashFile} from "./material.js";
import {photoEntry} from "./photo-entry.js";
import {preparePhoto,verifyCopy,checkImages,photoStep} from "./photo-form.js";
import {prepare,verifyText,videoEntry} from "./workflow.js";
import {declaration} from "./editor.js";
import {beforeSubmission,bookedReceipt,removeBooking} from "./scheduled-receipt.js";
const exact = value => new RegExp("^\\s*" + value + "(?:\\s*[时分])?\\s*$");
const dayPattern = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/;

export function bookingTime(value, platform, now = Date.now()) {
  if (typeof value !== "string" || !dayPattern.test(value)) throw Error("请填写北京时间 YYYY-MM-DD HH:mm");
  const epoch = Date.parse(value.replace(" ","T") + ":00+08:00");
  if (!Number.isFinite(epoch) || new Date(epoch + 8*3600000).toISOString().slice(0,16).replace("T"," ") !== value)
    throw Error("预约日期或时刻无效");
  const minutes = (epoch-now)/60000;
  if (minutes<=0) throw Error("预约时间已过");
  if (platform==="douyin" && (minutes<120 || minutes>14*1440)) throw Error("抖音允许预约 2 小时后至 14 天内");
  if (platform==="bilibili" && (minutes<5 || minutes>15*1440 || Number(value.slice(-2))%5)) throw Error("B站当前可选 5 分钟至 15 天，分钟按 5 分钟选择");
  return epoch;
}

function view(p,k) {
  if (k==="douyin") {const row=p.locator("label").filter({hasText:/^定时发布\s*$/});return {toggle:row,check:row.locator("input"),date:p.getByPlaceholder("日期和时间",{exact:true})};}
  if (k==="channels") {const row=p.locator(".post-time-wrap label").filter({hasText:/^\s*定时\s*$/});return {toggle:row,check:row.locator("input"),date:p.getByPlaceholder("请选择发表时间",{exact:true})};}
  if (k==="bilibili") {const row=p.locator(".time-container").filter({has:p.getByText("定时发布",{exact:true})}).locator(".switch-container").filter({visible:true});return {toggle:row,date:p.locator(".date-picker-date"),time:p.locator(".date-picker-timer")};}
  const row=p.locator(".custom-switch-card").filter({has:p.getByText("定时发布",{exact:true})});return {toggle:row.locator(".d-switch"),check:row.locator("input"),date:p.locator(".date-picker-container .d-datepicker-main")};
}
async function active(v) {
  if(v.check)return await v.check.count()===1 && await v.check.isChecked();
  return await v.toggle.isVisible() && await v.date.isVisible() && await v.time.isVisible();
}
async function dateText(k,v) {
  if(k==="douyin"||k==="channels")return v.date.inputValue();
  if(k==="bilibili")return (await v.date.innerText()).trim()+" "+(await v.time.innerText()).trim();
  return (await v.date.innerText()).trim().replace(/\s+/g," ");
}
export async function verifySchedule(p,t,{existing=false}={}) {
  if(!existing)bookingTime(t.scheduleAt,t.platform);
  const v=view(p,t.platform);
  const shown=await active(v) ? await dateText(t.platform,v) : "";
  if(shown!==t.scheduleAt)throw Error("未核实定时开关和预约时间。目标 "+t.scheduleAt+"，官网显示 "+(shown||"未启用"));
  return shown;
}
async function one(n,what) {
  await n.first().waitFor({state:"visible",timeout:3500});
  if(await n.count()!==1 || !await n.isEnabled())throw Error(what+"未在官网找到唯一可选项");
  const disabled=await n.evaluate(e=>!!e.closest('[aria-disabled=true],[disabled],[class*=disabled]'));
  if(disabled)throw Error(what+"在官网不可选");
  await n.click();
}
async function chooseTime(panels,selector,hour,minute) {
  if(await panels.count()!==2)throw Error("官网小时和分钟面板未就绪");
  for(const [index,value] of [hour,minute].entries()){
    const matching=panels.nth(index).locator(selector).filter({hasText:exact(value),visible:true});
    await one(matching,value);
  }
}
const calendars={
  xhs:{header:".d-datepicker-selector",next:".d-datepicker-header [class*=next]",day:".d-datepicker-cell:not(.disabled):not(.--color-text-placeholder)"},
  bilibili:{header:".date-picker-nav-title",next:".date-picker-nav-wrp [class*=next]",day:".date-picker-body-item.date-item,.date-picker-body-item.date-item-selected"},
  channels:{header:".weui-desktop-picker__panel_day .weui-desktop-picker__panel__hd",next:".weui-desktop-picker__panel_day .weui-desktop-btn__icon__right:visible",day:".weui-desktop-picker__table-row td a:not(.weui-desktop-picker__faded):not(.weui-desktop-picker__disabled)"}
};
async function selectDay(p,k,date) {
  const c=calendars[k],heading=p.locator(c.header).filter({visible:true}).first();
  const y=Number(date.slice(0,4)),m=Number(date.slice(5,7)),day=Number(date.slice(8));
  const inMonth=async()=>new RegExp(y+"年\\s*0?"+m+"月").test((await heading.innerText({timeout:2500})).replace(/\s+/g,""));
  if(!await inMonth()){await one(p.locator(c.next).filter({visible:true}),"下个月");if(!await inMonth())throw Error("官网日历未显示目标年月");}
  await one(p.locator(c.day).filter({visible:true,hasText:exact(String(day))}),"预约日期");
}
async function setSchedule(p,t) {
  const k=t.platform;bookingTime(t.scheduleAt,k);
  const offset=await p.evaluate(()=>new Date().getTimezoneOffset());
  if(offset!==-480)throw Error("请核对官网时区为北京时间后再预约");
  const v=view(p,k);
  if(k==="xhs"&&!await v.toggle.isVisible()){
    const more=p.getByText("更多设置",{exact:true}).filter({visible:true});
    if(await more.count()===1)await more.click();
  }
  if(!await active(v))await one(v.toggle,"定时选项");
  const [date,clock]=t.scheduleAt.split(" "),[hour,minute]=clock.split(":");
  await v.date.waitFor();
  if(k==="douyin"){
    await v.date.fill(t.scheduleAt);
    await v.date.press("Enter");await v.date.press("Tab");
    await verifySchedule(p,t);
    // Reopen and check the native calendar's committed state as well as the editable field.
    await v.date.click();
    const day=p.locator(".semi-datepicker-switch-date:visible"),time=p.locator(".semi-datepicker-switch-time:visible");
    await day.waitFor();
    if((await day.innerText()).trim()!==date || (await time.innerText()).trim()!==clock)
      throw Error("抖音日历尚未保存所填日期和分钟");
    await v.date.press("Escape");return verifySchedule(p,t);
  }
  const dayAlreadySelected=k==="xhs" && (await dateText(k,v)).split(" ")[0]===date;
  await v.date.click();
  if(!dayAlreadySelected)await selectDay(p,k,date);
  if(k==="xhs"){
    const panel=p.locator(".post-time-date-picker-popover-class:visible");
    const columns=panel.locator(".d-timepicker-timebar:visible");
    // The main field commits each selection. The minute click can close the
    // popover itself; clicking the field again during that transition reopens it.
    const waitDisplay=pattern=>v.date.filter({hasText:pattern}).waitFor({state:"visible",timeout:4000});
    const closeClock=async()=>{
      if(await panel.isVisible())await p.locator("input[placeholder*=标题]:visible").first().click();
      await panel.waitFor({state:"hidden",timeout:3000});
    };
    const pick=async(column,value,expected,label)=>{
      for(let attempt=0;attempt<2;attempt++){
        await closeClock();
        await v.date.click();
        const option=columns.nth(column).locator(".d-timepicker-time").filter({hasText:exact(value),visible:true});
        await one(option,label+value);
        try{await waitDisplay(expected);return;}catch(e){if(attempt)throw Error(label+value+"未保存，主表单显示 "+await dateText(k,v),{cause:e});}
      }
    };
    await waitDisplay(new RegExp("^"+date+"\\s"));
    if((await dateText(k,v)).slice(11,13)!==hour)
      await pick(0,hour,new RegExp("^"+date+"\\s+"+hour+":"),"预约小时 ");
    if(await dateText(k,v)!==t.scheduleAt)await pick(1,minute,t.scheduleAt,"预约分钟 ");
    await closeClock();
    return verifySchedule(p,t);
  }else if(k==="bilibili"){
    await v.time.click();
    await chooseTime(p.locator(".time-picker-panel-select-wrp:visible"),".time-picker-panel-select-item",hour,minute);
  }else{
    if(!await p.locator(".weui-desktop-picker__time__hour").isVisible()){
      if(!await p.locator(".weui-desktop-picker__time").isVisible())await v.date.click();
      await p.locator(".weui-desktop-picker__time .weui-desktop-picker__dt").click();
    }
    await one(p.locator(".weui-desktop-picker__time__hour:visible li").filter({hasText:exact(hour)}),"小时");
    await one(p.locator(".weui-desktop-picker__time__minute:visible li").filter({hasText:exact(minute)}),"分钟");
  }
  // A click on the schedule section heading closes the picker without submitting the form.
  const label={xhs:"定时发布",douyin:"发布时间",bilibili:"定时发布",channels:"定时发表"}[k];
  const title=p.getByText(label,{exact:true}).filter({visible:true}).first();
  if(await title.isVisible())await title.click();
  return verifySchedule(p,t);
}

async function submitControl(p,t) {
  const k=t.platform;
  if(new URL(p.url()).origin!==new URL(config(k).edit).origin)throw Error("编辑页域名变化");
  let button,options;
  if(k==="xhs"){
    button=p.locator("xhs-publish-btn:visible");
    if(await button.getAttribute("submit-text")!=="定时发布" || await button.getAttribute("submit-disabled")!=="false")throw Error("小红书未显示可用的定时发布按钮");
    const box=await button.boundingBox();
    if(!box || box.width<415 || box.height<47)throw Error("发布栏布局变化");
    options={position:{x:411,y:45}};
  }else if(k==="bilibili")button=p.getByText(/^(立即投稿|定时投稿|提交稿件)$/,{exact:true}).filter({visible:true});
  else button=p.getByRole("button",{name:k==="douyin"?/^(发布|定时发布)$/:/^(发表|定时发表)$/}).filter({visible:true});
  if(await button.count()!==1 || !await button.isEnabled())throw Error("当前成稿的提交入口不唯一或不可用");
  await button.click({...options,trial:true,timeout:5000});
  return ()=>button.click(options);
}

export async function runScheduled(session,s,cmd){
  const {ctx,id,job,dir}=session,{key,t,assets,photo,approval}=s,k=t.platform;
  const marker=path.join(home,"submissions",digest(["scheduled",key,t.account.selfPath||t.account.value,s.signature,t.scheduleAt])+".json");
  const stepPrefix=config(k).label+(photo?"图文":"视频");
  const scope=path.join(dir,key);await mkdir(scope,{recursive:true,mode:0o700});
  s.list??=await backgroundTab(ctx);
  let r=await read(marker);
  if(r&&r.approval!==approval && !(["prepare","submit"].includes(cmd.op)&&availableSubmission(r,id)))throw Error("相同账号、素材和预约时刻已有另一批提交记录");
  if(cmd.op==="prepare"){
    if(!availableSubmission(r,id))throw Error("该预约已有提交记录，使用 recover");
    s.previous=r;
    s.old=await beforeSubmission(s.list,t);
    if(job.testBatch && s.old.length)throw Error("后台已有同名稿，请给测试稿使用可区分的名称");
    s.prepared=null;
    if(s.edit&&!s.edit.isClosed())await s.edit.close();
    if(photo){
      s.edit=await photoEntry(ctx,k,t.account.value);
      s.proof=await preparePhoto(s.edit,t,assets);
    }else{
      s.edit=await videoEntry(ctx,await backgroundTab(ctx),k);
      s.proof=await prepare(s.edit,t,assets,scope,{opened:true});
    }
    const scheduledAt=await photoStep("设置预约时间",()=>setSchedule(s.edit,t),stepPrefix);
    s.prepared=digest([approval,key,s.proof,scheduledAt]);
    return {prepared:s.prepared,title:t.title,account:t.account.value,scheduledAt,proof:s.proof};
  }
  if(cmd.op==="submit"){
    if(!availableSubmission(r,id)||!s.prepared||cmd.approval!==approval||cmd.seen?.[key]!==s.prepared)throw Error("本次预约未准备好或已经点击过");
    if(photo){await verifyCopy(s.edit,t,assets,s.proof);await checkImages(s.edit,k,assets);}
    else {await verifyText(s.edit,t);if(k==="bilibili")await declaration(s.edit,config(k),t,t.declaration?.spec,false);}
    const click=await submitControl(s.edit,t);
    await photoStep("回读预约时间",()=>verifySchedule(s.edit,t),stepPrefix);
    r={state:"uncertain",platform:k,media:t.media,account:t.account.value,title:t.title,scheduleAt:t.scheduleAt,approval,baseline:s.old,session:id,started:new Date().toISOString(),...(s.proof?.skipped?{note:s.proof.skipped}:{})};
    await reserveSubmission(marker,id,s.previous,r);
    await click();await s.edit.waitForTimeout(2800);
  }
  if(cmd.op==="clean"){
    if(!job.testBatch||!job.receiptDir||!r?.desktop?.length||r.approval!==cmd.approval||JSON.stringify(cmd.seen?.[key])!==JSON.stringify(r.desktop.map(x=>x.sha256)))throw Error("仅可清理已核对桌面截图的本批测试预约");
    if(r.state==="removed")return {removed:true};
    for(const shot of r.desktop)if(await hashFile(shot.file)!==shot.sha256)throw Error("桌面截图已变化");
    await accountVerifier(ctx).verify(config(k),t.account);
    const old=r.state;await save(marker,{...r,state:"removing"});
    async function remove(){
      try{return await removeBooking(s.list,t,{...r,state:old},{waiting:s.awaitingOwner});}
      catch(e){if(e.handoff)s.awaitingOwner=true;throw e;}
    }
    let result;
    try {result=await remove();}
    catch(e){
      if(!e.handoff?.requiresVisibleLogin)throw e;
      // Chrome cannot display a headless challenge. Reopen the bound profile
      // only for this genuine handoff. Committed records remain recoverable.
      await session.reopenVisible();
      await accountVerifier(session.ctx).verify(config(k),t.account);
      s.list=await backgroundTab(session.ctx);result=await remove();
    }
    await save(marker,{...r,state:"removed"});return result;
  }
  if(!["submit","recover"].includes(cmd.op)||!r)throw Error("未找到可续查的本批投稿");
  if(r.state==="removed"||r.state==="receipt"&&r.verified)return r;
  const receipt=await bookedReceipt(s.list,t,r,job.receiptDir||scope,id+"-"+key,{history:cmd.op==="recover"});
  r=normalizeReceipt({...r,...receipt,state:receipt.verified===true?"receipt":"uncertain"});await save(marker,r);return r;
}
