import {readFile} from "node:fs/promises";
import path from "node:path";
import {capture,pixels} from "./evidence.js";

// Pure page function. Compare the visible crop, including local differences
// that a whole-image average would dilute on covers with a white background.
export async function visualDistance({original,preview,ratio,visibleOnly=false}) {
  async function sample(data){
    const image=await createImageBitmap(new Blob([Uint8Array.from(atob(data),c=>c.charCodeAt(0))]));
    const sw=Math.min(image.width,image.height*ratio),sh=sw/ratio;
    const ctx=new OffscreenCanvas(96,96).getContext("2d");
    ctx.imageSmoothingQuality="high";
    ctx.fillStyle="white";ctx.fillRect(0,0,96,96);
    ctx.drawImage(image,(image.width-sw)/2,(image.height-sh)/2,sw,sh,0,0,96,96);image.close();
    return ctx.getImageData(0,0,96,96).data;
  }
  const [a,b]=await Promise.all([sample(original),sample(preview)]);
  const blocks=new Array(64).fill(0);
  for(let p=0;p<96*96;p++){
    const i=p*4,block=Math.floor(p%96/12)+8*Math.floor(p/96/12);
    blocks[block]+=(Math.abs(a[i]-b[i])+Math.abs(a[i+1]-b[i+1])+Math.abs(a[i+2]-b[i+2]))/(12*12*3*255);
  }
  if(visibleOnly){
    // Exclude rounded corners and the bottom editing toolbar. The raw final
    // thumbnail still undergoes the stricter, full-image comparison.
    const center=blocks.filter((v,i)=>i%8>=1 && i%8<=6 && i>=8 && i<48);
    return center.reduce((sum,v)=>sum+v,0)/center.length;
  }
  blocks.sort((a,b)=>b-a);
  return (blocks[0]+blocks[1])/2;
}
export function finalCoverThreshold(ratio) {
  // Compression and glyph rasterization vary with each thumbnail's aspect.
  return ratio>1 ? 0.082 : ratio>0.7 ? 0.067 : 0.051;
}

// B站在主编辑页只展示首页封面。另一张从保存后重新打开的编辑器中核对。
async function savedBilibiliCovers(page,assets,dir) {
  const board=page.locator(".cover-editor-panel-canvas:visible");
  const main=page.locator(".cover-slot:not(.cover-add-pk) .cover-img:visible");
  if(await board.count() || await main.count()!==1)throw Error("B站已保存的主封面入口不唯一或弹窗尚未关闭");
  await main.click();
  await board.waitFor();
  try {
    const pair={};
    for(const [role,selector,ratio] of [["landscape",".editor_4_3",4/3],["wide",".editor_16_9",16/9]]) {
      const canvas=board.locator(selector+" canvas.lower-canvas:visible");
      await canvas.waitFor();
      const original=(await readFile(assets[role].file)).toString("base64");
      const end=Date.now()+7500,threshold=finalCoverThreshold(ratio);
      let consecutive=0,distance;
      do {
        const preview=await canvas.evaluate(n=>n.toDataURL("image/png").split(",")[1]);
        distance=await page.evaluate(visualDistance,{original,preview,ratio});
        consecutive=distance<=threshold ? consecutive+1 : 0;
        if(consecutive===2)break;
        await page.waitForTimeout(200);
      }while(Date.now()<end);
      if(consecutive!==2)throw Error("B站保存后 "+role+" 封面与原图不符，差值 "+distance.toFixed(3));
      pair[role]={role,distance,threshold,method:"reopened-saved-canvas"};
    }
    if(dir)pair.wide.evidence=await capture(page,board,path.join(dir,"bilibili-saved-pair.png"));
    return pair;
  }finally{
    await page.locator(".cover-editor-content-right:visible").getByText("取消",{exact:true}).click();
    await board.waitFor({state:"hidden"});
  }
}
async function displayedSource(tile){
  return tile.evaluate(el=>{
    const imgs=el.matches("img")?[el]:[...el.querySelectorAll("img")].filter(n=>n.getBoundingClientRect().width>0);
    if(imgs.length===1 && imgs[0].complete && imgs[0].naturalWidth>0)return imgs[0].currentSrc;
    const bg=getComputedStyle(el).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/);
    return bg?.[1]||null;
  });
}
// Compare the image actually bound to the visible editor slot. At 74 CSS pixels
// a persistent “编辑” badge can obscure most lettering in a screenshot.
async function thumbnailBytes(page,tile,src){
  if(!src)return null;
  if(src.startsWith("blob:") || src.startsWith("data:image/")){
    return tile.evaluate(async(el,url)=>{
      const image=await createImageBitmap(await (await fetch(url)).blob());
      const c=new OffscreenCanvas(image.width,image.height);
      c.getContext("2d").drawImage(image,0,0);image.close();
      const bytes=new Uint8Array(await (await c.convertToBlob()).arrayBuffer());
      let binary="";for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
      return btoa(binary);
    },src);
  }
  const url=new URL(src);
  if(url.protocol!=="https:" || url.username || url.password)return null;
  // Read only an already loaded image URL observed in this visible slot.
  if(!await tile.evaluate((el,url)=>performance.getEntriesByName(url).length>0 ||
      [el,...el.querySelectorAll("img")].some(n=>n.currentSrc===url&&n.complete&&n.naturalWidth),src))return null;
  const response=await page.request.get(src,{maxRedirects:0,timeout:4500});
  try{
    if(!response.ok() || !/^image\//i.test(response.headers()["content-type"]||""))return null;
    return (await response.body()).toString("base64");
  }finally{await response.dispose();}
}
export async function verifyFinalCovers(page,k,slots,assets,dir){
  const checks=[];
  const pair=k==="bilibili"?await savedBilibiliCovers(page,assets,dir):null;
  for(const slot of slots){
    if(pair && slot.role==="wide"){checks.push(pair.wide);continue;}
    let ratio=slot.role==="wide"?16/9:slot.role==="landscape"?4/3:k==="douyin"||k==="xhs"?3/4:9/16;
    const tile=page.locator(pair?".cover-slot:not(.cover-add-pk) .cover-img":slot.q.css).filter({visible:true});
    if(await tile.count()!==1)throw Error("最终封面槽位缺失或不唯一："+slot.role);
    const bounds=await tile.boundingBox();
    if(pair && (!bounds || Math.abs(bounds.width/bounds.height/ratio-1)>=0.05))
      throw Error("B站主编辑页未见已保存的 4:3 首页封面");
    if(k==="channels" && bounds)ratio=bounds.width/bounds.height;
    const original=(await readFile(assets[slot.role].file)).toString("base64");
    const until=Date.now()+7500;
    let distance,surfaceDistance,previous=null,consecutive=0,method,cachedSource,cachedBytes;
    do{
      const src=await displayedSource(tile);
      if(src!==cachedSource){
        cachedBytes=await thumbnailBytes(page,tile,src).catch(()=>null);cachedSource=src;
      }
      const raw=cachedBytes;
      const png=await tile.screenshot({animations:"disabled",scale:"device"});
      const {width,height}=pixels(png);
      if(width<32||height<32)throw Error("最终封面缩略图太小，无法核对");
      const rendered=png.toString("base64");
      method=raw?"final-slot-image+screen":"final-slot-screenshot";
      distance=await page.evaluate(visualDistance,{original,preview:raw||rendered,ratio});
      surfaceDistance=await page.evaluate(visualDistance,{original,preview:rendered,ratio,visibleOnly:true});
      const stable=src===await displayedSource(tile);
      const identity=src||method;
      consecutive=stable && surfaceDistance<=0.12 && distance<=finalCoverThreshold(ratio) ? (previous===identity?consecutive+1:1) : 0;
      previous=identity;
      if(consecutive===2)break;
      await page.waitForTimeout(200);
    }while(Date.now()<until);
    if(consecutive!==2)throw Error(slot.role+" 主编辑页最终封面与原图不同，差值 "+distance.toFixed(3)+"，未提交");
    checks.push({role:slot.role,distance,surfaceDistance,threshold:finalCoverThreshold(ratio),method,tile,...(pair?{savedEditor:pair.landscape}:{})});
  }
  return checks;
}
