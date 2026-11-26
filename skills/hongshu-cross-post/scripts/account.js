import path from "node:path";
import {mkdir} from "node:fs/promises";
import {save,read} from "./control.js";
import {platforms} from "./platforms.js";
import { setTimeout as delay } from "node:timers/promises";
import { find, owned } from "./page.js";
import { backgroundTab, requestHuman, launch, home } from "./runtime.js";

const challenges = [
  [/(?:请|需要|进行|完成|开始|通过).{0,6}(?:人脸识别|人脸验证|刷脸验证|扫脸验证)/, "请按官网指引完成本人面部验证"],
  [/(?:请输入.{0,8}(?:短信|手机)验证码|短信验证码.{0,6}(?:已发送|发送至)|短信登录)/, "请在官网完成短信登录或验证，验证码只填在官网"],
  [/(?:请.{0,8}(?:扫码|扫描二维码).{0,10}(?:登录|验证|确认)|扫码(?:即可)?登录|在手机上.{0,4}确认登录)/, "请用对应手机应用扫描官网二维码或在手机上确认"],
  [/(?:请.{0,5}完成.{0,4}(?:安全验证|身份验证)|拖动.{0,6}滑块)/, "请在官网完成页面显示的安全验证"]
];

export async function challengeOn(tab, cfg) {
  const top=new URL(tab.url());
  // The official creator homepage can redirect to a dedicated login origin.
  if(cfg===platforms.bilibili && top.hostname==="passport.bilibili.com" && top.pathname.startsWith("/login"))
    return "请在B站官网完成扫码登录";
  if(cfg===platforms.channels && top.hostname==="channels.weixin.qq.com" && top.pathname==="/login.html" &&
      await tab.getByText("登录视频号助手",{exact:true}).filter({visible:true}).count())
    return "请用微信扫描视频号助手的登录码";
  // Inspect only visible prompts on the official page. Never read a code or a QR payload.
  for (const frame of tab.frames()) {
    if (!owned(frame, cfg)) continue;
    if (frame.parentFrame() && !(await (await frame.frameElement()).isVisible())) continue;
    const dialog = frame.locator('dialog:visible,[role=dialog]:visible,.weui-desktop-dialog:visible,[class*=login-container i]:visible,[class*=login-modal i]:visible,.login__type__container:visible,[class*=captcha i]:visible');
    const texts = await dialog.allInnerTexts();
    if (!texts.length) {
      // Standalone login pages may have no dialog. Exclude unrelated account-sidebars.
      const onLogin = /\/(?:login|passport|verify|captcha)(?:\/|$)/i.test(new URL(frame.url()).pathname);
      if (onLogin) texts.push(await frame.locator("body").innerText({timeout:1500}));
      else {
        const visiblePrompts = frame.getByText(/^(?:短信登录|(?:微信)?扫码(?:即可)?登录|请(?:使用微信)?扫描二维码登录|请完成安全验证|请进行人脸识别|请在手机上确认登录)$/);
        for (const node of await visiblePrompts.all())
          if (await node.isVisible()) texts.push(await node.innerText());
      }
    }
    for (const text of texts)
      for (const [pattern, message] of challenges)
        if (pattern.test(text)) return message;
  }
  return null;
}

export async function boundAccount(platform,requested) {
  if(requested?.q && requested.value)return requested;
  if(requested!=null && (typeof requested.value!=="string" || !requested.value.trim()))
    throw Error("指定账号时请填写要核对的完整账号标识");
  const saved=await read(path.join(home,"accounts",platform+".json"));
  if(!saved?.display)throw Error("请先在专用分发浏览器核对"+platforms[platform].label+"本人账号；当前还没有绑定记录。");
  if(requested?.value && requested.value!==saved.display)throw Error("指定账号与已绑定账号不同，请核对目标账号");
  const account={value:saved.display,q:{text:saved.display},url:platforms[platform].home};
  if(platform==="bilibili"){
    if(!/^\d+$/.test(saved.uid||""))throw Error("B站需要核对本人空间 UID");
    account.selfPath="/"+saved.uid;account.url="https://space.bilibili.com"+account.selfPath;
  }
  if(requested?.selfPath && requested.selfPath!==account.selfPath)throw Error("指定账号 ID 与已绑定账号不同");
  return account;
}

const verifiers = new WeakMap();
export function accountVerifier(context) {
  if (verifiers.has(context)) return verifiers.get(context);
  const pending = new Map();
  const awaitingUser = new WeakSet();
  async function pause(tab, status, msg) {
    if (status === "needs_user" && !awaitingUser.has(tab)) {
      awaitingUser.add(tab);
      await requestHuman(tab,msg);
    }
    const error = Error(msg);
    error.handoff = {status, message:msg, pageKept:true};
    throw error;
  }
  const verifier = {
    async inspect(cfg) {
      const tab = pending.get(cfg);
      if (!tab || tab.isClosed()) throw Error("没有需要核对的账号页");
      if (awaitingUser.has(tab)) throw Error("官网验证页已置前，请由本人完成后重试原操作");
      return tab;
    },
    async verify(cfg, account) {
      const url = new URL(account.url || cfg.home);
      if (url.protocol !== "https:" || !cfg.hosts.includes(url.hostname)) throw Error("验号页必须位于官方站点");
      let tab = pending.get(cfg);
      if (!tab || tab.isClosed()) {
        tab = await backgroundTab(context);
        pending.set(cfg,tab);
        await tab.goto(url.href,{waitUntil:"domcontentloaded"});
      }
      const end = Date.now()+15000;
      do {
        let loc, prompt;
        try {
          prompt = await challengeOn(tab,cfg);
          if (!prompt && awaitingUser.has(tab)) {
            const current = new URL(tab.url());
            if (owned(tab,cfg)) {
              awaitingUser.delete(tab);
              if (current.pathname !== url.pathname || current.origin !== url.origin) {
                await tab.goto(url.href,{waitUntil:"domcontentloaded"});
                continue;
              }
            }
          }
          if (!prompt && [platforms.xhs,platforms.douyin].includes(cfg)) {
            const pattern=cfg===platforms.xhs?/^小红书账号[:：]\s*\S+$/:/^抖音号[:：]\s*\S+$/;
            const ids=await tab.getByText(pattern,{exact:true}).filter({visible:true}).allInnerTexts();
            if(ids.length===1 && pattern.test(account.value) && ids[0].trim()!==account.value)
              return pause(tab,"account_mismatch","官网当前账号为 "+ids[0].trim()+"，与本次绑定账号不同");
          }
          if (!prompt) loc = await find(tab,cfg,account.q);
        } catch (e) {
          if (e.matchCount > 1) return pause(tab,"identity_unreadable","账号区匹配到多项。保留页面供助手重新定位，不需要你提供验证码。");
          if (e.matchCount !== 0 && !/frame was detached|execution context was destroyed|Timeout.*1500ms/i.test(e.message)) throw e;
        }
        if (prompt) return pause(tab,"needs_user",prompt+"。完成后告诉助手继续。");
        if (loc) {
          const name=(await loc.innerText()).trim();
          if (account.selfPath && new URL(tab.url()).pathname.replace(/\/$/,"")!==account.selfPath) return pause(tab,"account_mismatch","个人空间的账号 ID 与清单不同");
          if (name===account.value) {
            const platform=Object.keys(platforms).find(k=>platforms[k]===cfg);
            if(platform){
              const folder=path.join(home,"accounts"),file=path.join(folder,platform+".json");
              const saved=await read(file),uid=platform==="bilibili"?account.selfPath?.slice(1):undefined;
              if(saved?.display!==name || (uid && saved?.uid!==uid)){
                await mkdir(folder,{recursive:true,mode:0o700});await save(file,{display:name,...(uid?{uid}:{})});
              }
            }
            await tab.close();
            pending.delete(cfg);
            return name;
          }
          if (name && !/^(?:加载中|加载中[.…]+|--+)$/.test(name)) return pause(tab,"account_mismatch","当前账号栏的文字与已确认账号不一致。请检查前台显示的账号；只有核对到同一账号才会继续。");
        }
        await delay(250);
      } while(Date.now()<end);
      if(cfg===platforms.bilibili && !awaitingUser.has(tab)){
        await tab.goto(cfg.home,{waitUntil:"domcontentloaded"});
        const prompt=await challengeOn(tab,cfg);
        if(prompt)return pause(tab,"needs_user",prompt);
        await tab.goto(url.href,{waitUntil:"domcontentloaded"});
      }
      return pause(tab,"identity_unreadable","未读到账号标识，页面已保留。由助手检查页面和定位；当前没有识别到需要本人验证的提示。");
    }
  };
  verifiers.set(context,verifier);
  return verifier;
}

// Check login before creating any uploads. A headless process can only show
// a real QR challenge by handing the same profile to a visible Chrome once.
export async function openForAccounts(targets, check) {
  let context = await launch();
  const results = {};
  const sweep = async () => {
    for (const target of targets) {
      try {results[target.platform] = await check(context,target);}
      catch (e) {if(!e.handoff)throw e;results[target.platform]=e.handoff;}
    }
  };
  try {
    await sweep();
    if (Object.values(results).some(v=>v?.requiresVisibleLogin)) {
      await context.close();
      context = await launch({visible:true});
      await sweep();
    }
    return {context,results};
  } catch(e) {await context.close();throw e;}
}
