import path from "node:path";
import {config,receiptDate,titleCards} from "./platforms.js";
import {verifyFinalCovers} from "./cover-check.js";
import {rowKey} from "./photo-receipt.js";
import {fillCovers} from "./covers.js";
import {topics,declaration,bilibiliDescription} from "./editor.js";
import {shortTitle,description,validateShortTitle,playerReceipt} from "./channels.js";
import {capture} from "./evidence.js";
import {displayText,readText} from "./page.js";

const layouts={
  douyin:['input[placeholder*="填写作品标题"]','.editor-comp-publish[contenteditable=true]','重新上传',null],
  xhs:['input[placeholder*="填写标题"]','.tiptap[contenteditable=true]','重新上传','xhs-publish-btn'],
  bilibili:['input[placeholder="请输入稿件标题"]',bilibiliDescription.css,'上传完成',':text-is("立即投稿")'],
  channels:[shortTitle.css,description.css,'封面预览','button:text-is("发表")']
};
const css=q=>JSON.stringify(q);
function spec(t){
  const dy=t.platform==="douyin";
  return {input:{css:dy?layouts.douyin[1]:'input[placeholder*="回车键Enter创建标签"]'},
    tokens:t.topics.map(n=>dy?{css:layouts.douyin[1]+' [contenteditable=false]:has-text('+css('#'+n)+')'}:{text:n}),
    choices:t.topics.map(n=>({css:':is(:text-is('+css('#'+n)+'),:text-is('+css(n)+')):not(.editor-comp-publish *):not(.editor-comp-publish)'}))};
}
export async function verifyText(page,t){
  const [title,body]=layouts[t.platform];
  if((await page.locator(title).inputValue())!==(t.shortTitle&&t.platform==="channels"?t.shortTitle:t.title))throw Error("标题变化");
  const core=s=>displayText(s).replace(/\s+/gu,"");
  if(core(await readText(page.locator(body)))!==core(t.body))throw Error("成稿正文与清单不同");
  await topics(page,config(t.platform),t,spec(t),true);
}
export async function videoEntry(c,p,k) {
  if(k!=="channels"){await p.goto(config(k).edit,{waitUntil:"domcontentloaded"});return p;}
  await p.goto(config(k).home,{waitUntil:"domcontentloaded"});
  const button=p.getByText("发表视频",{exact:true}).filter({visible:true});
  await button.first().waitFor();
  if(await button.count()!==1)throw Error("视频号首页投稿入口不唯一");
  const popup=p.waitForEvent("popup",{timeout:2500}).catch(()=>null);
  await button.click();
  const editor=(await popup)||p;
  if(editor!==p)await p.close();
  await editor.locator('input[type=file][accept*="video"]').first().waitFor({state:"attached"});
  return editor;
}
export async function uploadVideo(page,k,assets,dir){
  const ready=layouts[k][2];
  const video=page.locator(k==="bilibili"?'.bcc-upload-wrapper input[type=file][accept*=".mp4"]':'input[type=file][accept*="mp4" i],input[type=file][accept*="video" i]').first();
  await video.setInputFiles(assets.video.file,{timeout:45000});
  try { await page.getByText(ready,{exact:true}).filter({visible:true}).first().waitFor({timeout:assets.video.bytes<15000000?45000:300000}); }
  catch { const hints=await page.getByText(/上传失败|重新上传|上传中|上传完成|继续编辑|上次|重新选择|重试/).filter({visible:true}).allTextContents();
    const modal=page.getByText("继续编辑",{exact:true}).filter({visible:true});
    let dialog="";
    if(await modal.count()===1)dialog=await modal.evaluate(n=>n.parentElement.parentElement.innerText.slice(0,320));
    await page.screenshot({path:path.join(dir,"上传未完成.png")}).catch(()=>{});
    throw Error("等待上传完成超时："+hints.map(v=>v.slice(0,90)).slice(-5).join(" ")+" "+dialog); }
}
export async function prepare(page,t,assets,dir,{opened=false}={}){
  const k=t.platform,cfg=config(k),[title,body,ready]=layouts[k];
  if(!opened)await page.goto(cfg.edit,{waitUntil:"domcontentloaded"});
  await uploadVideo(page,k,assets,dir);
  const channelSlots=k==="channels"?await fillCovers(page,k,assets):null;
  await page.locator(title).fill(k==="channels"?t.shortTitle:t.title);
  if(k==="channels"){await page.locator(title).press("Tab");await validateShortTitle(page,t.shortTitle);}
  if(k==="bilibili"||!t.topics.length)await page.locator(body).fill(t.body);
  await topics(page,cfg,t,spec(t));
  for(const value of t.options||[])await page.getByText(value,{exact:true}).filter({visible:true}).click();
  await declaration(page,cfg,t,t.declaration?.spec,true);
  const slots=channelSlots||await fillCovers(page,k,assets);
  const checks=await verifyFinalCovers(page,k,slots,assets,dir);
  const tiles=checks.map(c=>c.tile).filter(Boolean);
  const proof=await capture(page,tiles[0],path.join(dir,k+"-covers.png"),tiles.length>1?tiles[0].or(tiles[1]):undefined);
  proof.slots=checks.map(({tile,...scores})=>scores);
  await verifyText(page,t);
  return {proof,roles:slots.map(s=>s.role),url:page.url(),account:t.account.value,title:t.title};
}
export async function clickSubmit(page,t,reserve){
  const cfg=config(t.platform);if(new URL(page.url()).origin!==new URL(cfg.edit).origin)throw Error("投稿页已改变");
  await verifyText(page,t);
  const btn=(t.platform==="douyin"?page.getByRole("button",{name:"发布",exact:true}):page.locator(layouts[t.platform][3])).filter({visible:true});
  if(await btn.count()!==1||!await btn.isEnabled())throw Error("发表按钮尚未就绪");
  let pos;
  if(t.platform==="xhs"){
    if(await btn.getAttribute("submit-text")!=="发布"||await btn.getAttribute("submit-disabled")!=="false")throw Error("发布组件未就绪");
    const box=await btn.boundingBox();
    if(!box||box.height<47||box.width<415)throw Error("发布栏布局有变");
    pos={position:{x:411,y:45}};
  }
  if(t.platform==="bilibili")await declaration(page,cfg,t,t.declaration?.spec,false);
  const messages=[];
  const watch=page.locator('[role=alert]:visible,.bcc-message:visible,.bcc-form-item-error:visible,[class*=error-tip]:visible,[class*=toast]:visible');
  await reserve();await btn.click(pos);
  for(let i=0;i<6;i++){await page.waitForTimeout(500);messages.push(...await watch.allInnerTexts().catch(()=>[]));}
  const modal=page.locator('[role=dialog]:visible,.bcc-dialog:visible,.weui-desktop-dialog:visible,.d-modal:visible');
  return {path:new URL(page.url()).pathname,messages:[...new Set(messages.filter(Boolean))],dialogs:await modal.allInnerTexts().catch(()=>[])};
}
export async function rows(page,t){
  return titleCards(page,t.platform,t.title);
}
export async function baseline(page,t){
  await page.goto(config(t.platform).list,{waitUntil:"domcontentloaded"});
  await page.locator(config(t.platform).listCard).first().waitFor({timeout:9000}).catch(async()=>{
    await page.getByText(/暂无作品|暂无相关视频|没有找到相关笔记|一个稿件都没有|暂无稿件|暂无笔记/).filter({visible:true}).first().waitFor({timeout:4000});
  });
  return (await (await rows(page,t)).allInnerTexts()).map(s=>s.match(receiptDate)?.[0]).filter(Boolean);
}
export async function receipt(page,t,record,dir,expectedSeconds){
  const until=Date.now()+45000;
  let checkPublished=false;
  do{
    await page.reload({waitUntil:"domcontentloaded"});
    let publishedTab;
    if(t.platform==="bilibili"){
      const published=page.locator(".secondTabs a.txt-item").filter({hasText:/^已发布(?:\s*\d+)?$/});
      if(checkPublished){
        await published.click();
        publishedTab=page.locator(".secondTabs a.txt-item.current").filter({hasText:/^已发布(?:\s*\d+)?$/});
        await publishedTab.waitFor();
      }
      const search=page.getByPlaceholder("搜索稿件",{exact:true});
      await search.fill(t.title);
      await search.press("Enter");
      checkPublished=!checkPublished;
    }
    const group=await rows(page,t);
    await group.first().waitFor({timeout:2500}).catch(()=>{});
    for(const row of await group.all()){
      const s=await row.innerText(),time=s.match(receiptDate)?.[0];
      let status=s.match(/原创审核中|审核中|已发布|已发表|已声明原创|转码中/)?.[0];
      if(t.platform==="bilibili"){
        if(!s.split("\n").some(line=>line.trim()===t.title))continue;
        if(publishedTab && await publishedTab.isVisible() && await row.locator('a[href*="BV"]').count() && await row.getByText("数据",{exact:true}).isVisible())status="已发布";
        else if(!s.split("\n").some(line=>line.trim()===status))continue;
      }
      if(!time||record.baseline.includes(time)||!status)continue;
      const localDate=time.replace(/[年月]/g,"-").replace("日","").replace(" ","T");
      const created=Date.parse(localDate),clicked=Date.parse(record.utc);
      if(!Number.isFinite(created)||created<clicked-60000||created>Date.now()+60000)continue;
      const duration=s.split("\n").map(v=>v.trim()).find(v=>/^(?:\d\d:)?\d\d:\d\d$/.test(v));
      const seconds=duration?.split(":").reduce((total,v)=>total*60+Number(v),0);
      if(t.platform!=="channels" && (!seconds || (expectedSeconds && Math.abs(seconds-expectedSeconds)>1)))continue;
      const proofRegion=publishedTab && status==="已发布"?publishedTab.or(row):undefined;
      const image=await capture(page,row,path.join(dir,t.platform+"-receipt.png"),proofRegion);
      const player=t.platform==="channels"?await playerReceipt(page,row,dir):undefined;
      if(expectedSeconds && player && Math.abs(player.seconds-expectedSeconds)>1)continue;
      return {key:await rowKey(row,t.platform),time,match:time,status,duration:player?.seconds??duration,image,player};
    }
    await page.waitForTimeout(750);
  }while(Date.now()<until);
  throw Error("作品管理未查到本次新记录；已保留点击记录，只能续查");
}
