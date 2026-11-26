import {config} from "./platforms.js";
import {backgroundTab,requestHuman} from "./runtime.js";
import {challengeOn} from "./account.js";
export const mpHome="https://mp.weixin.qq.com/";
export async function fitPhotoPage(p,k){
  if(k!=="douyin"&&k!=="mp")return;
  const size=p.viewportSize()||await p.evaluate(()=>({width:innerWidth,height:innerHeight}));
  if(size.width<1400)await p.setViewportSize({width:1400,height:Math.max(850,size.height)});
}
export async function photoIdentity(p,k,account){
  const url=k==="mp"?mpHome:config(k).home;
  await fitPhotoPage(p,k);
  await p.goto(url,{waitUntil:"domcontentloaded"});
  const id=k==="mp"?p.locator(".weui-desktop-account__info .acount_box-nickname, .weui-desktop-person_info .weui-desktop_name"):account?p.getByText(account,{exact:true}):p.getByText(k==="douyin"?/^抖音号[：:]\s*\S+$/:/^小红书账号[：:]\s*\S+$/);
  const visible=id.filter({visible:true}).first();
  if(!await visible.waitFor({timeout:12000}).then(()=>true,()=>false)){
    const prompt=await challengeOn(p,k==="mp"?{hosts:["mp.weixin.qq.com"]}:config(k));
    if(prompt)await requestHuman(p,prompt);
    const e=Error(prompt||"当前账号标识与目标未匹配，请核对页面上显示的账号");
    e.handoff={status:prompt?"needs_user":"identity_unreadable",message:e.message};throw e;
  }
  const value=(await visible.innerText()).trim();
  if(!value)throw Error("官网账号区为空");
  if(account&&value!==account)throw Error("官网当前登录账号与目标不一致，请本人切换后继续");
  return value;
}
export async function photoEntry(ctx,k,account,homePage){
  let p=homePage||await backgroundTab(ctx);
  try{
    if(!homePage)await photoIdentity(p,k,account);
    if(k!=="mp")await p.goto(config(k).edit,{waitUntil:"domcontentloaded"});
    const label=k==="mp"?"贴图":k==="douyin"?"发布图文":"上传图文";
    const candidates=p.getByText(label,{exact:true});await candidates.first().waitFor({state:"attached",timeout:15000});
    const hit=async node=>node.evaluate(e=>{
      const b=e.getBoundingClientRect(), h=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);
      return h&&(e===h||e.contains(h));
    });
    let chosen;
    if(k==="mp"){
      // The new-post panel can be below the fold or still rendering after login.
      const tiles=candidates.filter({visible:true});
      await tiles.first().waitFor({timeout:15000});
      if(await tiles.count()!==1)throw Error("公众号首页贴图入口不唯一");
      chosen=tiles.first();
      await chosen.scrollIntoViewIfNeeded();
    }else for(const node of await candidates.all())if(await hit(node)){chosen=node;break;}
    if(!chosen)throw Error("未找到可点击的"+label+"入口");
    if(k==="mp"){
      const next=ctx.waitForEvent("page",{timeout:4000}).catch(()=>null);
      await chosen.click();const editor=await next;
      if(editor){await p.close();p=editor;await fitPhotoPage(p,k);}
      await p.waitForLoadState("domcontentloaded");
    }else await chosen.click();
    const expected=new URL(k==="mp"?mpHome:config(k).edit).origin;
    if(new URL(p.url()).origin!==expected)throw Error("图文编辑页域名发生变化");
    return p;
  }catch(e){if(!homePage&&!p.isClosed())await p.close();throw e;}
}
