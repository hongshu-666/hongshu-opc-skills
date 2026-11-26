import {readFile} from "node:fs/promises";
import {setup} from "./runtime.js";
import {start,result,send,end} from "./control.js";
import {inventory} from "./material.js";
async function worker(id,file){
  const job=JSON.parse(await readFile(file,"utf8"));
  const {executeJob}=await import("./item.js");
  await executeJob(id,job);
}
const [cmd,id,arg,proof]=process.argv.slice(2);
try{
 let value;
 if(["run","batch-worker","query","pref"].includes(cmd))value=await (await import("./batch.js")).command(cmd,process.argv.slice(3));
 else if(cmd==="env"&&id==="bind")value=await (await import("./bind.js")).bind(process.argv.slice(4));
 else if(cmd==="setup"){
   value=await setup();
   const {environment}=await import("./environment.js");await environment({cache:true});
 }
 else if(cmd==="inventory")value=await inventory(id);
 else if(cmd==="start")value=await start(process.argv[1],id);
 else if(cmd==="result")value=await result(id,arg);
 else if(cmd==="worker"){await worker(id,arg);await end(id);}
 else if(["prepare","submit","recover","clean","close"].includes(cmd)){
  const input=proof?JSON.parse(await readFile(proof,"utf8")):{};
  value=await send(id,{...input,op:cmd,platform:arg||"all"});
 }else throw Error("用法：sh scripts/run.sh run 任务.json | run --status/--resume 批次号 | query --batch 批次号 | pref show/set/clear；Windows 使用 scripts/run.ps1");
 if(value)console.log(JSON.stringify(value));
 if(value?.error||Object.values(value||{}).some(x=>x?.error))process.exitCode=1;
}catch(e){if(cmd==="worker")await end(id,e.message);console.error(e.message.split("Call log")[0]);process.exitCode=1;}
