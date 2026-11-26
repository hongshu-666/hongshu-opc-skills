import path from "node:path";
import {capture} from "./evidence.js";
import {displayText} from "./page.js";

export const shortTitle = {css:'.post-short-title-wrap input'};
export const description = {css:'.input-editor[contenteditable]'};
export const cover = {role:"portrait",q:{css:".vertical-img-wrap img.cover-img-vertical"}};

export async function validateShortTitle(page, expected) {
  const wrap = page.locator(".post-short-title-wrap");
  if (await wrap.locator("input").inputValue() !== expected) throw Error("视频号短标题与清单不同");
  const error = (await wrap.innerText()).trim();
  if (error) throw Error("视频号短标题：" + error);
}

export async function bindChannelTopics(page, target, apply) {
  const ed = page.locator(description.css);
  if (apply) {
    await ed.fill(target.title);
    await ed.press("End");
    if (target.topics.length) await ed.press("Enter");
    for (const name of target.topics) {
      await ed.pressSequentially("#");
      await ed.pressSequentially(name,{delay:65});
      // Give the composer its debounce window before committing the topic with Space.
      await page.waitForTimeout(1050);
      await ed.press("End");
      await ed.press("Space");
    }
  }
  if(target.topics.length) await ed.locator('span.hl.topic[data-type="topic"]').nth(target.topics.length-1).waitFor();
  const bound = await ed.locator('span.hl.topic[data-type="topic"]').allTextContents();
  if (JSON.stringify(bound) !== JSON.stringify(target.topics.map(name=>"#"+name)) ||
      displayText(await ed.innerText()) !== displayText(target.body))
    throw Error("视频号描述或已绑定的话题与清单不同");
  return {bound};
}

export async function channelCover(page,file) {
  await page.locator(cover.q.css).click();
  const dialog = page.locator(".edit-cover-dialog .weui-desktop-dialog:visible");
  await dialog.locator('input[type=file][accept*="image"]').setInputFiles(file);
  await dialog.locator('.single-cover-uploader-wrap .finish-wrap img').waitFor();
  await dialog.getByRole("button",{name:"确认",exact:true}).click();
  await dialog.waitFor({state:"hidden"});
  return [cover];
}

export async function playerReceipt(page,row,runDir) {
  await row.locator("img.thumb").click();
  try {
    const player = page.locator(".full-screen-body:visible");
    await player.waitFor();
    const media = player.locator("video");
    await media.evaluate(async video=>{
      if (video.readyState < 1) await new Promise((ok,fail)=>{
        const timer=setTimeout(()=>fail(Error("播放器尚未载入时长")),8000);
        video.addEventListener("loadedmetadata",()=>{clearTimeout(timer);ok();},{once:true});
      });
    });
    const seconds = await media.evaluate(video=>video.duration);
    if (!Number.isFinite(seconds) || seconds<=0) throw Error("官方播放器未提供有效时长");
    return {seconds,image:await capture(page,player,path.join(runDir,"channels-player.png"))};
  } finally {
    await page.reload({waitUntil:"domcontentloaded"});
    await row.waitFor();
  }
}
