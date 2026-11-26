import {mkdir} from "node:fs/promises";
import path from "node:path";
import {home,backgroundTab,requestHuman} from "./runtime.js";
import {openForAccounts,challengeOn} from "./account.js";
import {config} from "./platforms.js";
import {photoIdentity,mpHome} from "./photo-entry.js";
import {save} from "./control.js";

export async function bind(keys) {
  if(!keys.length)throw Error("请指定需要绑定的平台");
  const site=k=>k==="mp"?{home:mpHome,hosts:["mp.weixin.qq.com"]}:config(k);
  const discovered=new Map(),tabs=new Map();
  async function probe(ctx,{platform:k}) {
    const cfg=site(k);
    let tab=tabs.get(k);
    if(!tab || tab.isClosed()){
      tab=await backgroundTab(ctx);tabs.set(k,tab);
      await tab.goto(k==="bilibili"?"https://space.bilibili.com/":cfg.home,{waitUntil:"domcontentloaded"});
    }
    const hint=await challengeOn(tab,cfg);
    if(hint){
      await requestHuman(tab,hint);
      const e=Error(hint);e.handoff={status:"needs_user",message:hint};throw e;
    }
    let account;
    if(k==="mp")account={display:await photoIdentity(tab,k)};
    else if(k==="bilibili"){
      const owner=tab.getByText("视角：我自己",{exact:true}).filter({visible:true});
      await owner.waitFor({timeout:15000}).catch(async()=>{
        const message=await challengeOn(tab,cfg);
        if(!message)throw Error("B站尚未显示本人空间，请核对官网登录状态");
        await requestHuman(tab,message);
        const e=Error(message);e.handoff={status:"needs_user",message};throw e;
      });
      const u=new URL(tab.url()),uid=u.pathname.match(/^\/(\d+)\/?$/)?.[1];
      if(u.origin!=="https://space.bilibili.com"||!uid)throw Error("B站本人空间未显示唯一 UID");
      account={display:(await owner.innerText()).trim(),uid};
    }else{
      const pattern={douyin:/^抖音号[：:]\s*\S+$/,xhs:/^小红书账号[：:]\s*\S+$/,channels:/^sph[\w-]{6,}$/}[k];
      const loc=tab.getByText(pattern,{exact:true}).filter({visible:true});
      await loc.first().waitFor({timeout:10000}).catch(async()=>{
        const message=await challengeOn(tab,cfg);
        if(!message)throw Error("官网未显示可核实的本人账号栏");
        await requestHuman(tab,message);
        const e=Error(message);e.handoff={status:"needs_user",message};throw e;
      });
      if(await loc.count()!==1)throw Error("本人账号标识不唯一");
      account={display:(await loc.innerText()).trim()};
    }
    discovered.set(k,account);return account.display;
  }
  const targets=[...new Set(keys)].map(k=>{config(k);return {platform:k};});
  const {context,results}=await openForAccounts(targets,probe);
  try{
    for(const t of targets){
      const k=t.platform;
      if(results[k]?.status==="needs_user"){
        console.log(JSON.stringify({platform:k,...results[k]}));
        const end=Date.now()+600000;
        while(Date.now()<end){
          await new Promise(ok=>setTimeout(ok,1000));
          if(await challengeOn(tabs.get(k),site(k)))continue;
          await probe(context,t);break;
        }
      }
      if(!discovered.has(k))throw Error("尚未从官网核实本人账号");
    }
    await mkdir(path.join(home,"accounts"),{recursive:true,mode:0o700});
    for(const [k,a] of discovered)await save(path.join(home,"accounts",k+".json"),a);
    return Object.fromEntries(discovered);
  }finally{await context.close();}
}
