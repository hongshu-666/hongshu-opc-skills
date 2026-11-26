import {readFile} from "node:fs/promises";
import {topics} from "./editor.js";
import {originalSwitch} from "./original.js";
import {config} from "./platforms.js";
import {readText,displayText} from "./page.js";

const fields={
  douyin:{title:'input[placeholder="添加作品标题"]',body:'.editor-comp-publish[contenteditable=true]',thumb:'[class^="img-"] > img',file:'input[multiple][type=file][accept*="image/png"]'},
  xhs:{title:'input[placeholder*="填写标题"]',body:'.tiptap[contenteditable=true]',thumb:'.format-img .img.preview',file:'input.upload-input[multiple][type=file]'},
  mp:{title:'.title-editor__input .ProseMirror',body:'.share-text__input .ProseMirror',thumb:'.image-selector__bottom-list-item',file:'.js_upload_btn_container input[type=file][multiple][accept*="image/bmp"]'}
};
export function actualTitle(t,m){return t.platform==="douyin"?(t.includeTitle?m.title:""):m.title;}
const coreLines=s=>String(s).replace(/[\u200b\ufeff]/g,"").split(/\r?\n/).map(displayText).filter(Boolean);
async function typeParagraphs(p,ed,text){
  await ed.fill("");await ed.focus();
  for(const [i,line] of text.split("\n").entries()){if(i)await ed.press("Enter");if(line)await p.keyboard.insertText(line);}
}
export async function checkImages(p,k,m){
  const nodes=p.locator(fields[k].thumb);
  await nodes.nth(m.photos.length-1).waitFor({state:"attached",timeout:40000});
  if(await nodes.count()!==m.photos.length)throw Error("页面图片张数与清单不同");
  if(k==="mp")await p.waitForFunction(({selector,count})=>{
    const es=[...document.querySelectorAll(selector)];
    const cov=[...document.querySelectorAll(".js_appmsg_thumb_new")];
    const covOk=!cov.length||cov.some(e=>/mmbiz\.qpic\.cn/.test(getComputedStyle(e).backgroundImage));
    return covOk&&!document.querySelector(".image-selector__preview-center .weui-desktop-loading")&&es.length===count&&es.every(e=>{const bg=getComputedStyle(e).backgroundImage;return /^url\(["']?https?:\/\//.test(bg)&&!/undefined|null|loading/i.test(bg)&&!e.querySelector(".weui-desktop-loading");});
  },{selector:fields.mp.thumb,count:m.photos.length},{timeout:60000});
  const uris=await nodes.evaluateAll(es=>es.map(e=>e.currentSrc||e.src||getComputedStyle(e).backgroundImage.match(/^url\(["']?(.+?)["']?\)$/)?.[1]));
  const thumbs=[],crops=[];
  for(const uri of uris){
    if(!uri)throw Error("有一张预览未生成");
    let bytes;const index=thumbs.length;let crop=null;
    if(/^(blob:|data:image\/)/.test(uri)){
      bytes=await p.evaluate(async u=>{const b=await (await fetch(u)).blob();return await new Promise((ok,fail)=>{const r=new FileReader();r.onload=()=>ok(r.result.split(",")[1]);r.onerror=fail;r.readAsDataURL(b);});},uri);
    }else{
      const u=new URL(uri,p.url());
      if(u.protocol!=="https:")throw Error("预览图地址无效");
      const r=await p.request.get(u.href,{timeout:10000});
      if(r.ok()&&/^image\//.test(r.headers()["content-type"]||""))bytes=(await r.body()).toString("base64");
      else{
        const n=nodes.nth(index);await n.scrollIntoViewIfNeeded();
        const b=await n.boundingBox();crop={width:b.width,height:b.height};
        bytes=(await n.screenshot({scale:"css",animations:"disabled"})).toString("base64");
      }
    }
    thumbs.push(bytes);crops.push(crop);
  }
  const originals=await Promise.all(m.photos.map(async f=>(await readFile(f.file)).toString("base64")));
  const scores=await p.evaluate(async ({originals,thumbs,crops})=>{
    const sample=async (b,crop)=>{
      const raw=Uint8Array.from(atob(b),c=>c.charCodeAt(0));const im=await createImageBitmap(new Blob([raw]));
      const c=new OffscreenCanvas(64,80),g=c.getContext("2d");g.fillStyle="white";g.fillRect(0,0,64,80);if(crop){const ratio=crop.width/crop.height,sw=Math.min(im.width,im.height*ratio),sh=sw/ratio;g.drawImage(im,(im.width-sw)/2,(im.height-sh)/2,sw,sh,0,0,64,80);}else g.drawImage(im,0,0,64,80);im.close();
      return g.getImageData(0,0,64,80).data;
    };
    const b=await Promise.all(thumbs.map(s=>sample(s,null))),cache=new Map();
    for(const crop of crops){const key=JSON.stringify(crop);if(!cache.has(key))cache.set(key,await Promise.all(originals.map(s=>sample(s,crop))));}
    return b.map((x,i)=>cache.get(JSON.stringify(crops[i])).map(y=>{let sum=0;for(let i=0;i<x.length;i+=4)sum+=Math.abs(x[i]-y[i])+Math.abs(x[i+1]-y[i+1])+Math.abs(x[i+2]-y[i+2]);return sum/(x.length/4*3*255);}));
  },{originals,thumbs,crops});
  if(scores.some((r,i)=>r[i]>.12||r.some((s,j)=>i!==j&&m.photos[i].sha256!==m.photos[j].sha256&&s<=r[i])))throw Error("官网预览与原图逐页比对失败："+JSON.stringify(scores.map(r=>r.map(s=>+s.toFixed(3)))));
  return {count:scores.length,distances:scores.map((r,i)=>+r[i].toFixed(4))};
}
function topicSpec(m){
  const ed=fields.douyin.body,q=JSON.stringify;
  return {input:{css:ed},tokens:m.topics.map(n=>({css:ed+' [contenteditable=false]:has-text('+q("#"+n)+')'})),choices:m.topics.map(n=>({css:':is(:text-is('+q("#"+n)+'),:text-is('+q(n)+')):not(.editor-comp-publish *):not(.editor-comp-publish)'}))};
}
function musicRequest(value) {
  if (value == null || value === "") return null;
  const spec = typeof value === "string" ? {title:value} : value;
  if (typeof spec.title !== "string" || !spec.title.trim()) throw Error("请填写要使用的歌名");
  const {duration, artist, source="search"} = spec;
  if (!["search","favorites"].includes(source) ||
      (duration != null && (typeof duration !== "string" || !/^\d{2}:[0-5]\d$/.test(duration))) ||
      (artist != null && (typeof artist !== "string" || !artist.trim())))
    throw Error("请核对配乐来源、歌手与 mm:ss 格式的时长");
  return {title:spec.title.trim(), source, duration, artist:artist?.trim()};
}
function musicField(p) {
  return p.locator('[class^="content-child-"]').filter({
    has:p.locator('span[class^="action-"]').filter({hasText:/^(选择|修改)音乐$/})
  });
}
function declarationField(p) {
  return p.locator("section").filter({has:p.getByText("自主声明",{exact:true})}).locator('[class^="selectBox-"]');
}
export async function photoStep(name, action, prefix="抖音图文") {
  try { return await action(); }
  catch (error) { throw new Error(`${prefix} · ${name}：${error.message}`, {cause:error}); }
}
async function selectMusic(p,request) {
  const field=musicField(p);
  await field.locator('span[class^="action-"]').click();
  const sheet=p.locator(".semi-sidesheet:visible").filter({has:p.getByPlaceholder("搜索音乐",{exact:true})});
  if(request.source==="favorites"){
    const tab=sheet.getByRole("tab",{name:"收藏",exact:true});
    await tab.click();
    if(await tab.getAttribute("aria-selected")!=="true")throw Error("音乐收藏页签未选中");
  }else{
    const search=sheet.getByPlaceholder("搜索音乐",{exact:true});
    await search.fill(request.title);
    await search.press("Enter");
    await sheet.getByRole("tab",{name:"收藏",exact:true}).waitFor({state:"hidden"});
  }
  const results=sheet.locator('[class^="music-collection-container-"]:visible');
  let rows=results.locator('[class^="card-wrapper-"]:visible').filter({has:p.locator('[class^="song-name-"]').and(p.getByText(request.title,{exact:true}))});
  if(request.duration)rows=rows.filter({has:p.locator(".song-duration").and(p.getByText(request.duration,{exact:true}))});
  if(request.artist)rows=rows.filter({has:p.locator(".song-author").and(p.getByText(request.artist,{exact:true}))});
  if(!await rows.first().waitFor({timeout:6500}).then(()=>true,()=>false))
    throw Error("当前音乐列表没有匹配的歌名、歌手与时长，请核对学员选择");
  if(await rows.count()!==1){
    const versions=await rows.evaluateAll(cards=>cards.slice(0,6).map(card=>
      [".song-author",".song-duration"].map(css=>card.querySelector(css)?.textContent?.trim()).join(" ")));
    throw Error("有多个同名版本，请按歌手和时长选择："+versions.join("、"));
  }
  const duration=(await rows.locator(".song-duration").innerText()).trim();
  await rows.hover();
  await rows.getByRole("button",{name:"使用",exact:true}).click();
  await sheet.waitFor({state:"hidden"});
  await field.locator('[class^="sub-desc-title-"]').and(p.getByText(request.title,{exact:true})).waitFor();
  if((await field.locator('[class^="sub-desc-duration-"]').innerText()).trim()!==duration)
    throw Error("官网已选音乐的时长与所选版本不同");
}
async function selectDeclaration(p,value){
  const field=declarationField(p);
  await field.scrollIntoViewIfNeeded();
  await field.click();
  const modal=p.locator(".semi-modal:visible").filter({has:p.getByText("请选择声明类型（单选）",{exact:true})});
  const row=modal.locator("label.semi-radio").filter({has:p.getByText(value,{exact:true})});
  await modal.waitFor();
  if(await row.count()!==1)throw Error("官网声明列表没有唯一匹配项："+value);
  await row.scrollIntoViewIfNeeded();
  await row.click();
  await row.locator('input[type="radio"]:checked').waitFor({state:"attached"});
  await modal.getByRole("button",{name:"确定",exact:true}).click();
  await modal.waitFor({state:"hidden"});
}
async function verifyDouyinOptions(p,t,prepared){
  const request=musicRequest(t.music),field=musicField(p);
  const title=field.locator('[class^="sub-desc-title-"]');
  const options={};
  if(request){
    options.music={title:(await title.innerText()).trim(),duration:(await field.locator('[class^="sub-desc-duration-"]').innerText()).trim()};
    const expectedDuration=prepared?.music?.duration ?? request.duration;
    if(options.music.title!==request.title || (expectedDuration && options.music.duration!==expectedDuration))
      throw Error("编辑页已选音乐与清单不同");
  }else if(await title.count())throw Error("本次未指定配乐，编辑页已有音乐，请核对");
  if(t.declaration){
    options.declaration=(await declarationField(p).innerText()).trim();
    if(options.declaration!==t.declaration)throw Error("编辑页已选自主声明与清单不同");
  }
  return options;
}

export async function verifyCopy(p,t,m,prepared){
  const f=fields[t.platform],title=await readText(p.locator(f.title)),value=await readText(p.locator(f.body));
  if(displayText(title)!==actualTitle(t,m))throw Error("官网标题与本次清单不同");
  if(JSON.stringify(coreLines(value))!==JSON.stringify(coreLines(m.caption)))throw Error("官网正文或分段与清单不同："+JSON.stringify(coreLines(value).map(s=>s.length))+" / "+JSON.stringify(coreLines(m.caption).map(s=>s.length)));
  if(t.platform!=="mp"&&m.topics.length)await topics(p,config(t.platform),{...t,topics:m.topics,body:m.caption},topicSpec(m),true);
  if(t.platform==="douyin")return photoStep("回读配乐与自主声明",()=>verifyDouyinOptions(p,t,prepared));
  if(t.platform==="xhs"&&t.original)return prepared?.skipped?{skipped:prepared.skipped}:photoStep("回读原创声明",()=>originalSwitch(p,{...t,declaration:{acceptOriginalTerms:true}},false),"小红书图文");
}
export async function preparePhoto(p,t,m){
  const k=t.platform,f=fields[k];
  if(k==="mp"){await p.waitForLoadState("load");await p.locator(f.title).waitFor();await p.waitForTimeout(1000);}
  await p.locator(f.file).setInputFiles(m.photos.map(f=>f.file));
  await p.locator(f.title).waitFor();
  if(k==="xhs"){
    const guide=p.locator(".feature-guide:visible").getByText("我知道了",{exact:true});
    if(await guide.isVisible())await guide.click();
  }
  const imageCheck=await checkImages(p,k,m);
  const title=p.locator(f.title),ed=p.locator(f.body);
  if(k!=="douyin"||t.includeTitle)await title.fill(actualTitle(t,m));
  if(k==="mp"||!m.topics.length)await typeParagraphs(p,ed,m.caption);
  else if(k==="douyin"){
    await ed.focus();await ed.press("ControlOrMeta+a");await ed.press("Backspace");
    const tags=m.topics.map(n=>"#"+n).sort((a,b)=>b.length-a.length);
    for(const [i,line] of m.caption.split("\n").entries()){
      if(i)await ed.press("Enter");let rest=line;
      while(rest){const hits=tags.map(tag=>({tag,at:rest.indexOf(tag)})).filter(h=>h.at>=0).sort((a,b)=>a.at-b.at);
        if(!hits.length){await p.keyboard.insertText(rest);break;}
        const {tag,at}=hits[0];if(at)await p.keyboard.insertText(rest.slice(0,at));
        await ed.pressSequentially("#");await p.keyboard.insertText(tag.slice(1));
        const choice=p.locator(topicSpec(m).choices[m.topics.indexOf(tag.slice(1))].css).filter({visible:true});
        await choice.click();rest=rest.slice(at+tag.length);
      }
    }
  }else await topics(p,config(k),{...t,topics:m.topics,body:m.caption},topicSpec(m));
  const orig=k==="xhs"&&t.original?await photoStep("原创声明",()=>originalSwitch(p,{...t,declaration:{acceptOriginalTerms:true}},true),"小红书图文"):null;
  if(k==="douyin"){
    const request=musicRequest(t.music);
    if(request)await photoStep("选择音乐",()=>selectMusic(p,request));
    if(t.declaration)await photoStep("选择自主声明",()=>selectDeclaration(p,t.declaration));
  }
  const options=await verifyCopy(p,t,m,orig);
  return {...imageCheck,...options};
}
