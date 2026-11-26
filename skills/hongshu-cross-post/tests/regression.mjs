import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,writeFile,symlink,rm} from "node:fs/promises";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import path from "node:path";
import os from "node:os";
import {normalizeReceipt} from "../scripts/control.js";
import {locate} from "../scripts/scheduled-receipt.js";
import {nextOperation} from "../scripts/batch.js";
import {makePlan} from "../scripts/plan.js";
import {rowKey} from "../scripts/photo-receipt.js";
import {mpQueryAction} from "../scripts/query.js";

test("已核验回执清掉历史续查动作和原因",()=>{
  assert.deepEqual(normalizeReceipt({state:"receipt",key:"123",next:"recover",reason:"列表延迟"}),{state:"receipt",key:"123"});
  assert.equal(normalizeReceipt({state:"receipt",verified:false}).state,"uncertain");
  assert.equal(normalizeReceipt({state:"uncertain",next:"recover"}).next,"recover");
});
test("无标题抖音图文按前缀、新标识和预约分钟唯一匹配",async()=>{
  const t={platform:"douyin",media:"photo",title:"开头",scheduleAt:"2099-01-03 18:00"};
  function card(id,time){
    const meta={locator:selector=>({allInnerTexts:async()=>[selector.includes("status")?"定时发布中":"定时: 2099年1月3日 "+time] ,filter(){return this;}})};
    return {scrollIntoViewIfNeeded:async()=>{},evaluate:async()=>[id,"","",""],locator:s=>
      s.includes("info-title")?{allInnerTexts:async()=>["开头正文"]}:s.includes("info-op")?meta:{first:()=>({evaluate:async()=>{}})}};
  }
  const cards=[card("old","18:00"),card("early","15:00"),card("new","18:00")];
  const list={filter(){return this;},all:async()=>cards},page={locator:()=>list};
  assert.equal((await locate(page,t,{baseline:["old"]})).key.id,"new");
  cards.push(card("second","18:00"));await assert.rejects(locate(page,t,{baseline:["old"]}),/多条/);
});
test("提交边界中断只能续查，已成功只跳过",()=>{
  assert.equal(nextOperation({state:"submitting"},{state:"uncertain"}),"recover");
  assert.equal(nextOperation({state:"uncertain",clicked:true},null),"recover");
  assert.equal(nextOperation({state:"submitting"},null),"prepare");
  assert.equal(nextOperation({state:"pending"},{state:"receipt"}),"skip");
});
test("从软链调用体检仍输出环境状态",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"crosspost-check-"));
  try{
    const src=fileURLToPath(new URL("../scripts",import.meta.url));
    const alias=path.join(dir,"linked");
    await symlink(src,alias,process.platform==="win32"?"junction":"dir");
    const child=spawnSync(process.execPath,[path.join(alias,"environment.js")],{env:{...process.env,CROSSPOST_HOME:path.join(dir,"empty")},encoding:"utf8"});
    const status=JSON.parse(child.stdout);assert.equal(status.ready,false);assert.ok(status.needs.length);
  }finally{await rm(dir,{force:true,recursive:true});}
});
test("公众号默认发表，预约、草稿偏好与测试批仅存草稿",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"crosspost-mp-"));
  try{
    await writeFile(path.join(dir,"发布文案.txt"),"标题\n\n正文\n");
    await writeFile(path.join(dir,"01.png"),Buffer.from("89504e470d0a1a0a","hex"));
    const snap=(p={})=>({accounts:{mp:{display:"测试号"}},preferences:{'["mp-photo","测试号"]':p}});
    const plan=(targets,ex={},p)=>makePlan({...ex,items:[{type:"photo",folder:dir,targets}]},snap(p));
    assert.equal((await plan(["mp"])).rows[0].action,"broadcast");
    assert.equal((await plan([{platform:"mp",action:"publish"}])).rows[0].action,"broadcast");
    assert.equal((await plan(["mp"],{},{action:"draft"})).rows[0].action,"draft");
    assert.equal((await plan(["mp"],{testBatch:true})).rows[0].action,"draft");
    await assert.rejects(plan([{platform:"mp",action:"broadcast"}],{testBatch:true}),/仅存草稿/);
    await assert.rejects(plan(["mp"],{scheduleAt:"2099-01-03 18:00"}),/预约未接入/);
    assert.equal((await plan([{platform:"mp",action:"draft"}],{scheduleAt:"2099-01-03 18:00"})).rows[0].action,"draft");
  }finally{await rm(dir,{force:true,recursive:true});}
});
test("公众号发表标识稳定且查询按动作分流",async()=>{
  assert.deepEqual([{action:"broadcast"},{action:"publish"},{action:"draft"},{}].map(mpQueryAction),["broadcast","broadcast","draft","draft"]);
  const row=w=>({innerText:async()=>w+"\n已发表\n标题",locator:()=>({count:async()=>1,first:()=>({getAttribute:async()=>"https://mp.weixin.qq.com/s/id1"})})});
  assert.equal(await rowKey(row("今天 13:30"),"mp","broadcast"),await rowKey(row("昨天 13:30"),"mp","broadcast"));
});
