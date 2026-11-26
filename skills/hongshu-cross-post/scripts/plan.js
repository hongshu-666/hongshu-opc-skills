import path from "node:path";
import {home} from "./runtime.js";
import {read,save} from "./control.js";
import {withFileLease} from "./lease.js";
import {bookingTime} from "./schedule.js";
import {material,platformAssets,digest} from "./material.js";
import {photoMaterial} from "./photo-material.js";
import {boundAccount} from "./account.js";
import {validateFields,platformBody} from "./editor.js";

const prefsFile=path.join(home,"preferences.json");
const supported={photo:["douyin","xhs","mp"], video:["douyin","xhs","channels","bilibili"]};
const prefKeys={"douyin-photo":["music","declaration","includeTitle"],"xhs-photo":["original"],"mp-photo":["action"]};

function checkedPrefs(scope, values) {
  if (!values || Array.isArray(values) || typeof values!=="object") throw Error("偏好需要 JSON 对象");
  for (const [key,v] of Object.entries(values)) {
    if (!prefKeys[scope]?.includes(key)) throw Error("该平台不支持偏好 "+key);
    if (key==="action" && v!=="draft") throw Error("公众号偏好只可记住存草稿");
    if (["original","includeTitle"].includes(key) && typeof v!=="boolean") throw Error("偏好需要 true 或 false");
    if (key==="declaration" && (typeof v!=="string" || !v.trim())) throw Error("声明需为平台选项原文");
    if (key==="music" && !(typeof v==="string" && v.trim() || v && typeof v.title==="string" && v.title.trim())) throw Error("配乐缺曲名");
  }
  return values;
}
function applyItemChoices(target,item,scope){
  const t={...target};
  for(const field of prefKeys[scope]||[]){
    if(!Object.hasOwn(t,field) && Object.hasOwn(item,field))t[field]=item[field];
  }
  return t;
}
export async function pref([op="show",scope,json]) {
  if(!["show","set","clear"].includes(op))throw Error("pref show | set | clear");
  if(op==="show" && !scope)return await read(prefsFile)||{};
  if (!Object.hasOwn(prefKeys,scope)) throw Error("请选择支持偏好的平台-体裁");
  const account=(await read(path.join(home,"accounts",scope.split("-")[0]+".json")))?.display;
  if(!account) throw Error("请先绑定当前平台账号");
  const key=JSON.stringify([scope,account]);
  if(op==="show")return {scope,account,values:(await read(prefsFile))?.[key]||{}};
  return withFileLease("preferences",async()=>{
    const p=await read(prefsFile)||{};
    if(op==="set")p[key]={...p[key],...checkedPrefs(scope,JSON.parse(json))};
    else delete p[key];
    await save(prefsFile,p);return {scope,account,values:p[key]||{}};
  });
}
function scheduleChecks(rows) {
  const last=new Map(),warnings=[];
  for(const row of rows.filter(r=>r.at).sort((a,b)=>a.at.localeCompare(b.at))){
    const key=JSON.stringify([row.platform,row.accountId]);
    const prior=last.get(key);
    if(prior?.at===row.at)throw Error(prior.key+" 与 "+row.key+" 同账号同一分钟预约冲突");
    if(prior && Date.parse(row.at.replace(" ","T")+":00+08:00")-Date.parse(prior.at.replace(" ","T")+":00+08:00")<7200000)
      warnings.push(prior.key+" 与 "+row.key+" 排期相邻不足两小时");
    last.set(key,row);
  }
  return warnings;
}
export async function readAssets(item) {
  if(item.type==="photo")return photoMaterial(item);
  return material(item);
}
export function assetHash(a) {
  return a.photos ? digest([a.signature,a.title,a.caption]) : digest(Object.entries(a).map(([role,v])=>[role,v.sha256]));
}
// Snapshot only the selected accounts and their active preferences before a
// detached process can submit. An explicit false or null always wins.
export async function preferenceSnapshot(input) {
  const saved=await read(prefsFile)||{},snap={preferences:{},accounts:{},effective:[]};
  for(const [index,item] of (input.items??[input]).entries()){
    const type=item.type||({photo:"photo","single-now":"video"})[input.mode];
    for(const target of item.targets??input.targets??[]){
      const t=typeof target==="string"?{platform:target}:target;
      if(!supported[type]?.includes(t.platform))throw Error("目标平台或体裁无效");
      const scope=t.platform+"-"+type;
      const binding=await read(path.join(home,"accounts",t.platform+".json"));
      snap.accounts[t.platform]=binding;
      const account=t.account?.value||binding?.display;
      const key=JSON.stringify([scope,account]);
      snap.preferences[key]=saved[key]||{};
      const choices=applyItemChoices(t,item,scope);
      const values=Object.fromEntries(Object.entries(snap.preferences[key]).filter(([field])=>!Object.hasOwn(choices,field)));
      if(Object.keys(values).length)snap.effective.push({key:(index+1)+"-"+scope,account,values});
    }
  }
  return snap;
}
export async function makePlan(input,snapshot=undefined) {
  if(input.mode && !["single-now","photo","scheduled"].includes(input.mode))throw Error("任务模式无法识别");
  const items=input.items ?? [{...input,type:input.type||({photo:"photo","single-now":"video"})[input.mode]}];
  if(!Array.isArray(items)||!items.length)throw Error("请提供作品清单 items");
  const preferences=snapshot?.preferences||await read(prefsFile)||{}, rows=[];
  for(const [idx,item] of items.entries()){
    const type=item.type,targets=item.targets??input.targets;
    if(!supported[type]||!Array.isArray(targets)||!targets.length||!path.isAbsolute(item.folder||""))throw Error("每篇需指定体裁、素材目录绝对路径和平台");
    if(item.videoPath && !path.isAbsolute(item.videoPath))throw Error("videoPath 需为绝对路径");
    const used=new Set();
    const assetsForItem=await readAssets({...item,targets:targets.map(t=>typeof t==="string"?{platform:t}:t)});
    for(const raw of targets){
      const supplied=typeof raw==="string"?{platform:raw}:raw;
      const t=applyItemChoices(supplied,item,supplied.platform+"-"+type);
      const k=t.platform, scope=k+"-"+type, key=(idx+1)+"-"+scope;
      if(!supported[type].includes(k)||used.has(k))throw Error(key+" 平台重复或不支持此体裁");used.add(k);
      if([item.scheduleAt,input.scheduleAt,t.scheduleAt].some(value=>value!=null&&typeof value!=="string"))throw Error(key+" 预约时刻无效");
      const inherited=t.scheduleAt??item.scheduleAt??input.scheduleAt;
      const at=k==="mp"?null:inherited;
      if(k==="mp" && (t.scheduleAt!=null || (inherited!=null && t.action!=="draft")))throw Error(key+" 公众号预约未接入，仅可明确挂存草稿");
      if((input.mode==="scheduled" && k!=="mp" || t.action==="schedule") && !at)throw Error(key+" 缺少预约时间");
      const binding=snapshot ? snapshot.accounts[k] : await read(path.join(home,"accounts",k+".json"));
      const account=t.account?.value||binding?.display;
      if(!account)throw Error(key+" 首次使用请先核对并绑定账号");
      if(t.account && binding?.display && t.account.value!==binding.display)throw Error(key+" 账号与本机绑定不符");
      const accountId=k==="bilibili"?(t.account?.selfPath||"/"+(binding?.uid||"")):account;
      const saved=checkedPrefs(scope,preferences[JSON.stringify([scope,account])]||{}), applied={};
      for(const [f,v] of Object.entries(saved))if(!Object.hasOwn(t,f)){t[f]=v;applied[f]=v;}
      if(applied.original===true)t.originalFromPref=true;
      t.account=type==="video" || at ? await boundAccount(k,t.account||{value:account}) : {value:account};
      const rawAction=t.action??(k==="mp"?(input.testBatch||input.cleanup?"draft":"broadcast"):at?"schedule":"publish");
      const action=k==="mp"&&rawAction==="publish"?"broadcast":rawAction;
      if(k==="mp"?!["draft","broadcast"].includes(action):action!==(at?"schedule":"publish"))throw Error(key+" 动作与预约意图冲突");
      if(action==="broadcast"&&(input.testBatch||input.cleanup))throw Error("测试批次公众号仅存草稿");
      t.action=action;
      if(type==="video"){
        for(const f of ["title","body","topics","durationSeconds","shortTitle","declaration","options"])t[f]??=item[f];
        t.topics??=[];t.body??="";
        if(!t.title?.trim())throw Error(key+" 缺少视频标题");
        if(["douyin","xhs"].includes(k)){
          const missing=t.topics.filter(n=>!t.body.includes("#"+n));
          t.body=[t.body,...missing.map(n=>"#"+n)].filter(Boolean).join(" ");
        }
      }
      const source={...item,targets:[t]}; delete source.scheduleAt;delete source.items;
      const assets=type==="photo"?assetsForItem:platformAssets(assetsForItem,k);
      if(type==="photo" && k!=="douyin"&&!assets.title)throw Error(key+" 缺标题");
      if(type==="video")source.video??=assets.video.name;
      const common={testBatch:input.testBatch,receiptDir:input.receiptDir,cleanup:input.cleanup};
      const job=at?{...common,mode:"scheduled",scheduleAt:at,items:[source]}:{...source,...common,mode:type==="photo"?"photo":"single-now"};
      const execution=await compileJob(job,assets);
      rows.push({execution,key,platform:k,type,accountId,account,at:at||null,action,job,signature:assetHash(assets),applied});
    }
  }
  return {rows,warnings:scheduleChecks(rows)};
}
// Normalize the legacy submission of one or more targets and preserve its receipt keys.
// Batch planning passes the already inspected assets; the mailbox reads its own input.
export async function compileJob(job,inspected,{recover=false}={}) {
  const scheduled=job.mode==="scheduled",photoJob=job.mode==="photo";
  if(!scheduled && !photoJob && job.mode!=="single-now")throw Error("无法识别任务体裁");
  if(!scheduled && (job.scheduleAt!=null||job.targets?.some(t=>t.scheduleAt!=null||t.action==="schedule")))throw Error("预约清单缺少预约模式");
  const items=scheduled?job.items:[job],tasks=[],accountByPlatform=new Map();
  if(!Array.isArray(items)||!items.length)throw Error("预约任务缺少作品清单");
  for(const [index,item] of items.entries()){
    const type=scheduled?item.type:photoJob?"photo":"video",photo=type==="photo";
    if(!supported[type] || !item.targets?.length)throw Error("请核对体裁及目标平台");
    const assets=inspected??await readAssets({...item,type});
    if(scheduled && !photo && !item.video && !item.videoPath)item.video=assets.video.name;
    for(const input of item.targets){
      const k=input.platform,key=scheduled?k+"-"+type:k;
      if(!supported[type].includes(k) || tasks.some(s=>s.key===key))throw Error("不支持或重复的投稿目标 "+key);
      const t=scheduled && k!=="mp"?{...input,media:type,title:photo?assets.title:input.title??item.title,
        body:input.body??item.body??"",topics:input.topics??item.topics??[],scheduleAt:input.scheduleAt??job.scheduleAt}:{...input};
      if(scheduled && k!=="mp"){
        if(!recover)bookingTime(t.scheduleAt,k);
        if(k==="douyin"){
          t.captionPrefix=(photo?assets.body:t.body||"").trim().slice(0,12);
          if(photo && !t.includeTitle)t.title=assets.body.split("\n")[0].slice(0,18);
        }
        if(!t.title)throw Error("预约稿缺标题或可核对的正文开头");
      }
      if(k==="mp"){
        if(t.action==="publish")t.action="broadcast";
        if(!["draft","broadcast"].includes(t.action) || t.action==="broadcast"&&(scheduled||job.testBatch||job.cleanup))
          throw Error("公众号定时或测试仅存草稿");
        if(scheduled && (t.scheduleAt!=null||!item.targets.some(v=>["douyin","xhs"].includes(v.platform))))throw Error("公众号只能随同篇预约图文挂存草稿");
      }else if(photo && !scheduled && t.action!=="publish")throw Error("请指定图文发布动作");
      if(!photo || scheduled && k!=="mp")t.account=await boundAccount(k,t.account);
      if(t.account && !t.account.value?.trim())throw Error("指定的账号不能为空");
      if(k==="bilibili"){
        const url=new URL(t.account.url),self=t.account.selfPath;
        if((scheduled || url.hostname==="space.bilibili.com") && !/^\/\d+$/.test(self||"") || scheduled && url.pathname!==self)throw Error("需要本人空间 UID");
      }
      const identity=JSON.stringify(t.account);
      if(accountByPlatform.has(k) && accountByPlatform.get(k)!==identity)throw Error("同一平台的目标账号不同");
      accountByPlatform.set(k,identity);
      if(!photo){
        if(!t.title?.trim()||typeof t.body!=="string")throw Error("请补齐标题和正文");
        if(scheduled && ["douyin","xhs"].includes(k)){
          const missing=t.topics.filter(name=>!t.body.includes("#"+name));
          t.body=[t.body,missing.map(name=>"#"+name).join(" ")].filter(Boolean).join("\n");
        }
        if(k==="channels")t.body=[t.title,t.topics.map(n=>"#"+n).join(" ")].filter(Boolean).join("\n");
        validateFields(t);t.body=platformBody(t);
        if(k==="xhs"&&[...t.title].length>20||k==="douyin"&&[...t.title].length>30||["xhs","douyin"].includes(k)&&[...t.body].length>1000)throw Error(k+" 标题或正文超限");
      }
      tasks.push({key,t,photo,index,assets,signature:photo?assets.signature:assets.video.sha256});
    }
  }
  const {assets}=tasks[0],targets=tasks.map(s=>s.t);
  const approval=scheduled?digest({job,assets:tasks.map(s=>s.signature)}):photoJob?
    digest({mode:job.mode,targets,title:assets.title,caption:assets.caption,signature:assets.signature,testBatch:job.testBatch,receiptDir:job.receiptDir}):
    digest({targets,assets,durationSeconds:job.durationSeconds,cleanup:job.cleanup,testBatch:job.testBatch});
  return {tasks,approval};
}
