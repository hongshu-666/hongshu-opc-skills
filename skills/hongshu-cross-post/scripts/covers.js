import {readFile} from "node:fs/promises";
import {channelCover} from "./channels.js";
import {createHash} from "node:crypto";
import {setTimeout as wait} from "node:timers/promises";

async function previewBytes(panel) {
  const canvas = panel.locator("canvas.lower-canvas");
  return createHash("sha256").update(await canvas.evaluate(e => e.toDataURL("image/png"))).digest("hex");
}

async function bilibiliCovers(page, standard, wide) {
  const board = page.locator(".cover-editor-panel-canvas");
  const standardPanel = board.locator(".editor_4_3");
  let firstHash;
  for (const [ratio, file] of [["4_3", standard], ["16_9", wide]]) {
    const panel = board.locator(".editor_" + ratio);
    await panel.click();
    const active = board.locator(".active").filter({has: page.locator(".editor_" + ratio)});
    await active.waitFor();
    const sync = active.locator(".sync-checkbox");
    if (await sync.evaluate(e => e.classList.contains("bcc-checkbox-checked"))) await sync.click();
    if (await sync.evaluate(e => e.classList.contains("bcc-checkbox-checked"))) throw Error("双比例同步仍开启");
    await page.locator(".cover-editor-panel-select .cover-upload input[type=file]").setInputFiles(file);
    // Wait for the new preview to finish rendering before switching aspect ratios.
    await wait(800);
    let last = await previewBytes(panel);
    for (let i = 0; i < 12; i++) {
      await wait(250);
      const current = await previewBytes(panel);
      if (current === last) break;
      last = current;
      if (i === 11) throw Error("封面预览仍在变化");
    }
    if (ratio === "4_3") firstHash = last;
  }
  if (firstHash !== await previewBytes(standardPanel)) throw Error("设置个人空间封面后首页推荐封面发生变化，请重新核对两张原图");
  
}


async function waitForCover(page,canvas,file,ratio){
  const original=(await readFile(file)).toString("base64");
  const end=Date.now()+10000;
  let score;
  do{
    const preview=(await canvas.screenshot({animations:"disabled"})).toString("base64");
    score=await page.evaluate(async({original,preview,ratio})=>{
      const sample=async(data)=>{
        const bitmap=await createImageBitmap(new Blob([Uint8Array.from(atob(data),c=>c.charCodeAt(0))]));
        const sw=Math.min(bitmap.width,bitmap.height*ratio),sh=sw/ratio;
        const c=new OffscreenCanvas(48,48),g=c.getContext("2d");
        // The editing board surrounds the actual crop with grey gutters.
        g.drawImage(bitmap,(bitmap.width-sw)/2,(bitmap.height-sh)/2,sw,sh,0,0,48,48);
        bitmap.close();return g.getImageData(0,0,48,48).data;
      };
      const [a,b]=await Promise.all([sample(original),sample(preview)]);
      let all=0,bottom=0;
      for(let i=0;i<a.length;i+=4){
        const e=Math.abs(a[i]-b[i])+Math.abs(a[i+1]-b[i+1])+Math.abs(a[i+2]-b[i+2]);
        all+=e;if(i>=a.length/2)bottom+=e;
      }
      return Math.max(all,2*bottom)/(48*48*3*255);
    },{original,preview,ratio});
    if(score<.105)return;
    await wait(200);
  }while(Date.now()<end);
  throw Error("封面画布与对应原图不一致，差值 "+score.toFixed(3));
}

export async function fillCovers(page,platform,assets) {
  if(platform==="channels") return channelCover(page,assets.portrait.file);
  if(platform==="bilibili"){
    const board=page.locator(".cover-editor-panel-canvas");
    if(!await board.isVisible()){
      const add=page.getByText("添加主封面",{exact:true});
      if(await add.isVisible())await add.click();else await page.locator(".cover-slot .cover-img").click();
    }
    await bilibiliCovers(page,assets.landscape.file,assets.wide.file);
    await page.getByText("完成",{exact:true}).click();
    await board.waitFor({state:"hidden"});
    return [{role:"landscape"},{role:"wide"}];
  }
  if(platform==="xhs"){
    const tip=page.getByText("我知道了",{exact:true});
    if(await tip.isVisible() && await page.getByText(/视频可以PK封面啦/).isVisible())await tip.click();
    const tile=page.locator(".default--ai-cover-layout");
    await tile.hover();await page.getByText("编辑封面",{exact:true}).click();
    const preview=page.locator(".single-note img.cover:visible").first();
    await preview.evaluate(el=>el.decode());
    const previous=await preview.evaluate(el=>el.currentSrc);
    const uploaded=page.locator(".uploaded-thumbnail");
    if(await uploaded.isVisible()) await uploaded.locator(".uploaded-thumbnail-clear").click();
    await page.locator('.upload-btn input[type=file][accept*="image/jpeg"]').setInputFiles(assets.portrait.file);
    await uploaded.waitFor();
    await uploaded.click();
    await uploaded.locator("img").evaluate(el=>el.decode());
    await page.waitForFunction(previous=>Array.from(document.querySelectorAll(".single-note img.cover")).some(el=>
      el.getBoundingClientRect().width>0 && el.currentSrc.startsWith("blob:") &&
      el.currentSrc!==previous && el.complete && el.naturalWidth>0),previous,{timeout:12000});
    await preview.evaluate(el=>el.decode());
    const done=page.getByRole("button",{name:"完成",exact:true});
    await done.click();await done.waitFor({state:"hidden"});await page.locator(".cover-plugin-title").hover();
    return [{role:"portrait",q:{css:".default--ai-cover-layout"}}];
  }
  if(platform!=="douyin")throw Error("此平台未接入封面编辑");
  const slots=[["portrait","竖封面3:4"],["landscape","横封面4:3"]];
  const panel=page.locator('[class*=selectArea]:visible input.semi-upload-hidden-input');
  const result=[];
  for(const [role,label] of slots){
    const prompt=page.locator(".dy-creator-content-modal-wrap:visible").filter({hasText:"设置横封面获更多流量"});
    if(role==="landscape" && await prompt.isVisible())await prompt.getByRole("button",{name:"设置横封面",exact:true}).click();
    else await page.getByText(label,{exact:true}).locator("xpath=../..").click();
    await panel.waitFor({state:"attached"});await panel.setInputFiles(assets[role].file);
    const done=page.getByText("完成",{exact:true}).filter({visible:true});
    await done.waitFor();
    const canvas=done.locator("xpath=ancestor::*[.//canvas][1]").locator("canvas.lower-canvas:visible");
    await waitForCover(page,canvas,assets[role].file,role==="portrait"?3/4:4/3);
    await done.click();
    if(role==="portrait")await Promise.race([prompt.waitFor({timeout:8000}),done.waitFor({state:"hidden",timeout:8000})]);
    else await done.waitFor({state:"hidden"});
    result.push({role,q:{css:'div[class^="coverControl-"]:has-text("'+label+'") img'}});
  }
  return result;
}
