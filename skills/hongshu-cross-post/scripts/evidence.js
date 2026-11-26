import path from "node:path";
import {writeFile} from "node:fs/promises";
import {randomUUID,createHash} from "node:crypto";
import {inflateSync} from "node:zlib";

// Chrome screenshots are non-interlaced 8-bit RGB/RGBA PNGs. Inspect the saved pixels, not the file size.
export function pixels(png) {
  if (png.readUInt32BE(0)!==0x89504e47 || png.toString("ascii",12,16)!=="IHDR") throw Error("留图不是 PNG");
  const w=png.readUInt32BE(16), h=png.readUInt32BE(20), stride=({2:3,6:4})[png[25]];
  if (!stride || png[24]!==8 || png[28]!==0 || !w || !h || w*h>24000000) throw Error("不支持的留图像素格式或尺寸");
  const parts=[];
  for(let i=8;i+12<=png.length;){const n=png.readUInt32BE(i);if(i+n+12>png.length) throw Error("PNG 不完整");
    if(png.toString("ascii",i+4,i+8)==="IDAT") parts.push(png.subarray(i+8,i+8+n));i+=n+12;}
  const bytes=w*stride, data=inflateSync(Buffer.concat(parts),{maxOutputLength:(bytes+1)*h});
  if(data.length!==(bytes+1)*h) throw Error("截图像素不完整");
  let previous=Buffer.alloc(bytes), line=Buffer.alloc(bytes), offset=0;
  const freq=new Uint32Array(256), raster=createHash("sha256");
  for(let y=0;y<h;y++){
    const filter=data[offset++];if(filter>4)throw Error("PNG 滤波无效");
    for(let x=0;x<bytes;x++){
      const left=x>=stride?line[x-stride]:0, top=previous[x], corner=x>=stride?previous[x-stride]:0;
      const guess=left+top-corner, a=Math.abs(guess-left), b=Math.abs(guess-top), c=Math.abs(guess-corner);
      const pred=[0,left,top,(left+top)>>1,a<=b&&a<=c?left:b<=c?top:corner][filter];
      line[x]=(data[offset++]+pred)&255;
    }
    for(let x=0;x<bytes;x+=stride){const alpha=stride===4?line[x+3]/255:1;
      freq[Math.round(alpha*(.299*line[x]+.587*line[x+1]+.114*line[x+2])+(1-alpha)*255)]++;}
    raster.update(line);
    [previous,line]=[line,previous];
  }
  const used=[...freq.keys()].filter(i=>freq[i]);
  if(used.at(-1)-used[0]<16 || w*h-Math.max(...freq)<Math.max(12,w*h*.001))
    throw Error("截图为空白或近似纯色，未取得有效留图");
  return {width:w,height:h,pixelHash:raster.digest("hex"),sha256:createHash("sha256").update(png).digest("hex")};
}
// Serialize capture and validate saved pixels even when the tab stays in the background.
let captureQueue=Promise.resolve();
export function capture(page,loc,file,tiles) {
  const result=captureQueue.then(()=>captureVisible(page,loc,file,tiles));
  captureQueue=result.catch(()=>{});
  return result;
}
async function captureVisible(page,loc,file,tiles) {
  await loc.scrollIntoViewIfNeeded();
  await loc.evaluate(async el=>{
    await el.ownerDocument.fonts.ready;

  });

  let lastError;
  for(let attempt=0;attempt<5;attempt++){
    const options={scale:"css",animations:"disabled",caret:"hide",style:":focus,:focus-visible{outline:none!important;box-shadow:none!important}"};
    let png;
    if(tiles){
      const clip=await tiles.evaluateAll(nodes=>{
        if(nodes.length!==2)throw Error("未见双封面");
        const boxes=nodes.map(e=>e.getBoundingClientRect()), x=Math.floor(Math.min(...boxes.map(b=>b.left))), y=Math.floor(Math.min(...boxes.map(b=>b.top)));
        return {x:x+scrollX,y:y+scrollY,width:Math.ceil(Math.max(...boxes.map(b=>b.right)))-x,height:Math.ceil(Math.max(...boxes.map(b=>b.bottom)))-y};
      });
      png=await page.screenshot({...options,clip});
    }else png=await loc.screenshot(options);
    try{
      const proof=pixels(png);
      try{await writeFile(file,png,{flag:"wx",mode:0o600});}
      catch(e){
        if(e.code!=="EEXIST")throw e;
        file=path.join(path.dirname(file),path.basename(file,".png")+"-"+randomUUID()+".png");
        await writeFile(file,png,{flag:"wx",mode:0o600});
      }
      return {file,...proof};
    }catch(e){lastError=e;}
    await page.waitForTimeout(180);
  }
  throw lastError;
}
