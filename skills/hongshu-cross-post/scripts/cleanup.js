import path from "node:path";
import {readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import {save,read} from "./control.js";
import {find} from "./page.js";

async function evidence(targets,markerFor,approval,dir) {
  for (const t of targets) {
    const r=await read(markerFor(t));
    if (r?.approval!==approval || !["receipt","removing","removed"].includes(r.state) || !r.desktop?.length)
      throw Error("请先核清待清理范围的桌面回执");
    for (const {file,sha256} of r.desktop) {
      if(path.dirname(path.resolve(file))!==dir || createHash("sha256").update(await readFile(file)).digest("hex")!==sha256)
        throw Error("桌面回执路径或内容已变化");
    }
  }
}
export async function cleanup({page,cfg,t,a,job,markerFor,approval,verify}) {
  const dir=job.cleanup?.receiptDir;
  if (!dir || !path.isAbsolute(dir) || (job.cleanup?.afterAllReceipts!==true && job.cleanup?.perPlatform!==true) || a.approval!==approval)
    throw Error("本批未指定留证后清理");
  await evidence(job.cleanup.afterAllReceipts===true?job.targets:[t],markerFor,approval,dir);
  const file=markerFor(t), record=await read(file);
  if(a.op==="remove")await verify(t.platform,t.account);
  const hasMatch=async()=>{
    const nodes=page.getByText(t.title,{exact:false}).filter({visible:true});
    const times=page.getByText(record.time,{exact:false}).filter({visible:true});
    return (await nodes.count())>0 && (await times.count())>0;
  };
  if (a.op==="checkRemoved") {
    if (!["removing","removed"].includes(record.state)) throw Error("尚未尝试删除本批稿件");
    await page.reload({waitUntil:"domcontentloaded"});
    let ready;
    for(let i=0;i<30 && !ready;i++) {
      try { ready=await find(page,cfg,a.listReady); }
      catch(e){if(e.matchCount!==0) throw e; await page.waitForTimeout(500);}
    }
    if(!ready) throw Error("刷新后列表仍未加载，请继续核对");
    if (await hasMatch()) throw Error("列表仍有相同标题和时间，请核实同稿，不能报已删除");
    const next={...record,state:"removed"};await save(file,next);return {removed:true};
  }
  if (a.op==="confirmRemove") {
    if (record.state!=="removing") throw Error("没有本批待确认删除");
    const dialog=a.dialogNode||await find(page,cfg,a.dialog);
    if (!/删除|移除/.test(await dialog.innerText()) ||
        !await dialog.evaluate(e=>e.matches('[role=dialog],dialog,[class*=dialog i],[class*=modal i]')))
      throw Error("请定位到本次删除确认框");
    const ok=dialog.getByRole("button",{name:/^(?:删除|确定|确认|确认删除|确定删除)$/});
    if (await ok.count()!==1) throw Error("删除确认按钮不唯一");
    await ok.click(); return {next:"checkRemoved"};
  }
  if (record.state!=="receipt") throw Error("已尝试删除，请核对待确认框或刷新查结果");
  const row=await find(page,cfg,a.row);
  const text=await row.innerText();
  if(![t.title,record.time,record.match].every(v=>v && text.includes(v)) ||
     !await row.evaluate(e=>e.tagName!=="BODY" && e.tagName!=="HTML"))
    throw Error("待删行与审核回执不一致");
  await row.hover();
  let trigger;
  if(t.platform==="channels") trigger=row.getByText("删除",{exact:true}).locator("..").locator(".opr-item");
  if(t.platform==="xhs") trigger=row.locator(".note-card__action-btn--del");
  if(t.platform==="douyin") trigger=row.getByText("删除作品",{exact:true});
  if(t.platform==="bilibili") {
    await row.locator(".more-btn").hover();
    trigger=row.getByText("删除稿件",{exact:true});
  }
  if(!trigger || await trigger.count()!==1 || !await trigger.isVisible()) throw Error("回执行内未定位到唯一删除入口");
  await save(file,{...record,state:"removing"});await trigger.click();return {next:"confirmRemove 或 checkRemoved"};
}

export async function desktopProof(dir, files, shots) {
  if(!Array.isArray(files)||files.length!==shots.length) throw Error("请先将全部原图另存桌面、逐张打开核对");
  return await Promise.all(files.map(async(file,i)=>{
    if(!path.isAbsolute(file)||path.dirname(path.resolve(file))!==dir) throw Error("截图必须位于清单指定的桌面目录");
    const hash=createHash("sha256").update(await readFile(file)).digest("hex");
    if(hash!==shots[i].sha256) throw Error("桌面截图与官网原图不一致");
    return {file,sha256:hash};
  }));
}
