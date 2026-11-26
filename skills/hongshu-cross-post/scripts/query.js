import {setTimeout as delay} from "node:timers/promises";
import path from "node:path";
import {home,launch,backgroundTab} from "./runtime.js";
import {read} from "./control.js";
import {ledger} from "./batch.js";
import {boundAccount,accountVerifier} from "./account.js";
import {config,receiptDate} from "./platforms.js";
import {listing,locate} from "./scheduled-receipt.js";
import {openList,rowKey} from "./photo-receipt.js";
import {photoIdentity} from "./photo-entry.js";
import {withLease} from "./lease.js";

export async function historical(record) {
  if(record.platform&&record.account)return record;
  if(!/^[0-9a-f-]{36}$/.test(record.session||""))return record;
  const ready=await read(path.join(home,"sessions",record.session,"ready"));
  if(!ready || ready.approval!==record.approval || ready.items?.length!==1)return record;
  const [platform,media]=ready.items[0].split("-");
  const account=ready.identities?.[platform];
  if(typeof account!=="string")return record;
  return {...record,platform,media,account};
}
function argsMap(args){
  const opts={};
  for(let i=0;i<args.length;i++){
    const k=args[i];
    if(["--local","--login"].includes(k)){opts[k.slice(2)]=true;continue;}
    if(!["--batch","--item","--platform","--type","--date"].includes(k)||!args[i+1]||args[i+1].startsWith("--"))throw Error("query --batch 批次 [--item 键] 或 --platform 平台 [--date 日期] [--local]");
    opts[k.slice(2)]=args[++i];
  }
  if(opts.item&&!opts.batch)throw Error("查询单项需要批次号");
  if(opts.date&&!/^\d{4}-\d\d-\d\d$/.test(opts.date))throw Error("日期使用 YYYY-MM-DD");
  return opts;
}
export function mpQueryAction(r){
  return r?.action==="broadcast"||r?.action==="publish"?"broadcast":"draft";
}
async function checkPage(ctx,page,k,rows,opts){
  const saved=await read(path.join(home,"accounts",k+".json"));
  if(!saved?.display)throw Error("未绑定账号");
  if(k==="mp")await photoIdentity(page,k,saved.display);
  else await accountVerifier(ctx).verify(config(k),await boundAccount(k));
  const views=k==="mp"
    ?[{action:"broadcast",sel:".publish_record_history .weui-desktop-mass__content",tag:"[发表记录] "},{action:"draft",sel:".weui-desktop-card[data-appid]",tag:"[草稿箱] "}]
    :[{action:null,sel:config(k).listCard,tag:""}];
  const results=new Array(rows.length), visible=[];
  const matchesDate=s=>!opts.date||s.replace(/年|月|[/.]/g,"-").replace(/日/g,"").includes(opts.date);
  for(const v of views){
    const bucket=rows.map((r,i)=>[r,i]).filter(([r])=>!v.action||mpQueryAction(r)===v.action);
    if(v.action && !bucket.length && opts.batch)continue;
    if(v.action)await openList(page,{platform:k,action:v.action});
    else await listing(page,{platform:k});
    const cards=page.locator(v.sel).filter({visible:true}), allCards=await cards.all();
    for(const [r,i] of bucket){
      const row={file:r.file,title:r.title,at:r.scheduleAt,...(v.action?{action:v.action}:{}),ledgerState:r.state};
      try{
        if(r.account!==saved.display)throw Error("记录账号与当前绑定不一致");
        if(r.scheduleAt){
          const t={platform:k,media:r.media||"video",title:r.title,scheduleAt:r.scheduleAt,includeTitle:r.includeTitle};
          const hit=await locate(page,t,r,false,true);
          if(!hit)throw Error("当前列表未唯一核实该稿，保留原状态");
          const text=await hit.r.innerText();
          const scheduleText=text.split("\n").filter(line=>/预约|定时|将于/.test(line)).join(" ");
          const date=scheduleText.match(receiptDate)?.[0].replace(/[年月]/g,"-").replace(/日/g,"").replace(/-(\d)(?=[- ])/g,"-0$1").slice(0,16);
          const minute=hit.booking?.minute||(k!=="xhs" && date===r.scheduleAt?date:undefined);
          Object.assign(row,{verified:!!minute,status:hit.booking?.status||(minute?"已回读预约时刻":"已定位同稿，预约分钟待核"),observedMinute:minute,key:hit.key.id,display:text.slice(0,180)});
        }else{
          if(!r.key)throw Error("旧记录缺作品编号，保留原状态");
          const hits=[];
          for(const card of allCards){
            const id=v.action==="draft"?await card.getAttribute("data-appid"):await rowKey(card,k,v.action);
            if(id===r.key)hits.push(card);
          }
          if(hits.length!==1)throw Error("当前列表未唯一核实该稿");
          Object.assign(row,{verified:true,key:r.key,display:(await hits[0].innerText()).slice(0,180)});
        }
      }catch(e){row.verified=false;row.reason=e.message.split("Call log")[0];}
      results[i]=row;
    }
    if(!opts.batch)for(const s of (await cards.allInnerTexts()).map(t=>t.trim().slice(0,350)).filter(Boolean))
      if(matchesDate(s))visible.push(v.tag+s);
  }
  const output={platform:k,account:saved.display,results:results.filter(Boolean)};
  return opts.batch?output:{...output,scope:k==="mp"?"当前可见的发表记录与草稿箱":"当前可见的作品或草稿列表",visible};
}
export async function query(args) {
  const opts=argsMap(args);
  let rows=await Promise.all((await ledger()).map(historical)), plan,state;
  if(opts.batch){
    if(!/^[0-9a-f]{24}$/.test(opts.batch))throw Error("批次号无效");
    const dir=path.join(home,"batches",opts.batch);
    plan=await read(path.join(dir,"plan.json"));state=await read(path.join(dir,"state.json"));
    if(!plan||!state)throw Error("批次尚无已冻结的任务清单");
    if(opts.item&&!state.items[opts.item])throw Error("批次内没有该任务键");
    const sessions=new Map(plan.rows.filter(t=>!opts.item||opts.item===t.key).map(t=>[state.items[t.key].session,t]));
    rows=rows.filter(r=>sessions.has(r.session)).map(r=>{
      const t=sessions.get(r.session),src=t.job.items?.[0]||t.job;
      return {...r,platform:t.platform,media:t.type,account:t.account,action:r.action||t.action,includeTitle:src.targets[0].includeTitle};
    });
  }else if(!opts.platform)throw Error("请指定批次或平台");
  if(opts.platform && opts.platform!=="mp")config(opts.platform);
  if(opts.platform)rows=rows.filter(r=>r.platform===opts.platform);
  if(opts.type)rows=rows.filter(r=>r.media===opts.type);
  if(opts.date)rows=rows.filter(r=>r.scheduleAt?.startsWith(opts.date));
  const local=rows.map(r=>({file:r.file,platform:r.platform,account:r.account,title:r.title,at:r.scheduleAt,state:r.state}));
  const items=state&&Object.entries(state.items).filter(([key])=>!opts.item||key===opts.item)
    .map(([key,r])=>({key,state:r.state,clicked:rows.some(v=>v.session===r.session && v.state==="receipt")?true:r.clicked??(["submitting","uncertain"].includes(r.state)||rows.some(v=>v.session===r.session)?null:false),reason:r.reason,next:r.next}));
  if(opts.local)return {local,items};
  const platforms=opts.platform?[opts.platform]:[...new Set(rows.map(r=>r.platform))];
  if(!platforms.length)return {local,items,message:"本批所选目标尚无提交记录"};
  return withLease("profile",async()=>{
    const ctx=await launch({visible:!!opts.login});const output=[];
    try{
      for(const k of platforms){
        const page=await backgroundTab(ctx);
        try{
          const until=Date.now()+900000;
          let prompted=false;
          for(;;){
            try{output.push(await checkPage(ctx,page,k,rows.filter(r=>r.platform===k),opts));break;}
            catch(e){if(!opts.login || e.handoff?.status!=="needs_user" || Date.now()>=until)throw e;
              if(!prompted){console.error("等待本人完成官网验证");prompted=true;}await delay(4000);}
          }
        }
        catch(e){output.push({platform:k,verified:false,reason:e.message});}
        finally{await page.close();}
      }
    }finally{await ctx.close();}
    return {local,items,backends:output};
  });
}
