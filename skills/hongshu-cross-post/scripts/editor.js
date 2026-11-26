import {bindChannelTopics} from "./channels.js";
import {biliDeclaration,originalSwitch} from "./original.js";
import {find, readText, displayText} from "./page.js";

async function editorAction(loc, hasJob, where) {
  const info = await loc.evaluate(e=>{
    const el=e.closest("button,a,[role=button],label") || e;
    const label=(el.innerText || el.getAttribute("aria-label") || el.title || "").trim();
    return {label, description:[label,el.getAttribute("aria-label"),el.title,el.getAttribute("href")].filter(Boolean).join(" "),
      submit:el.matches('button[type=submit],input[type=submit]'),
      dialog:(el.closest('dialog,[role=dialog],[class*=modal i],[class*=popover i],[class*=dialog i]')?.innerText||"").slice(0,600)};
  });
  if (!hasJob || where!=="edit") {
    if(!["扫码登录","二维码登录","登录","刷新二维码"].includes(info.label)) throw Error("请先进入本次编辑页");
  } else if (!info.label || info.label.length>110 || info.submit ||
    /提交|^(立即)?发布$|投稿|发表|删除|移除|退出登录|切换账号|充值|购买|同意协议|暂存离开|存草稿|授权登录/.test(info.description) ||
    (/^(确定|确认|完成|是|继续)$/.test(info.label) && /删除|移除|确认.{0,6}(发布|投稿)|付费|切换账号/.test(info.dialog))) {
    throw Error("此控件涉及提交、账户或对外操作，请使用该动作的专用流程");
  }
  await loc.click();
}

async function bindTopics(page, body, topics, verifyOnly=false) {
  const ed=page.locator('.tiptap[contenteditable=true]');
  if (!Array.isArray(topics) || !topics.length) throw Error("请列明正文中须绑定的话题，名称不含 #");
  const names=[...new Set(topics)];
  for (const name of names) if (!name || !body.includes("#"+name)) throw Error("请核对正文与话题名");
  if (!verifyOnly) {
    await ed.fill("");
    const pattern = names.slice().sort((a,b)=>b.length-a.length).map(n=>n.replace(/[.*+?^$(){}|[\]\\]/g,"\\$&")).join("|");
    const parts=body.split(new RegExp("(#(?:"+pattern+"))","g"));
    for (const s of parts) {
      if (!s) continue;
      if(s.startsWith("#") && names.includes(s.slice(1))) {
        await ed.pressSequentially("#"); await page.keyboard.insertText(s.slice(1));
        const exact=page.locator(".items:visible .item .name").filter({hasText:new RegExp("^"+s.replace(/[.*+?^$(){}|[\]\\]/g,"\\$&")+"$")});
        await exact.click();
        // The editor appends one space; the user's next segment supplies its own separator.
        if ((await ed.innerText()).endsWith("\u00a0")) await ed.press("Backspace");
      } else {
        const lines=s.split("\n");
        for(let i=0;i<lines.length;i++){if(i) await ed.press("Enter"); if(lines[i]) await page.keyboard.insertText(lines[i]);}
      }
    }
  }
  const bound=await ed.locator("a.tiptap-topic[data-topic]").evaluateAll(nodes=>nodes.map(e=>{
    const t=JSON.parse(e.getAttribute("data-topic"));return t.id && t.name;
  }));
  if (names.some(n=>!bound.includes(n)) || displayText(await readText(ed))!==displayText(body))
    throw Error("话题链接或正文未回读一致，保留编辑页核对");
  return {bound};
}

function topicNames(t) {
  if(!Array.isArray(t.topics) || !t.topics.every(n=>typeof n==="string" && n.trim()===n && n && !n.startsWith("#")))
    throw Error("本平台的话题/标签需要逐项列明，无话题用空数组");
  const names=[...new Set(t.topics)];
  if(t.platform!=="bilibili") for(const m of t.body.matchAll(/(?:^|\s)#([^\s#，。！？、]+)/gu))
    if(!names.includes(m[1]))throw Error("正文中有未核对的话题 "+m[1]);
  return names;
}
export const bilibiliDescription = {css: '.ql-editor[contenteditable="true"][data-placeholder*="相关信息"]'};

export function platformBody(t) {
  if (t.platform !== "bilibili" || !t.topics.length) return t.body;
  const names = t.topics.slice().sort((a,b) => b.length-a.length)
    .map(name => name.replace(/[.*+?^$(){}|[\]\\]/g, "\\$&"));
  // URLs can contain title-like fragments. Match only complete, explicitly selected tags.
  const tag = "#(?:" + names.join("|") + ")(?=$|[\\s#，。！？、；：,.!?;:）】》])";
  const token = new RegExp("https?://[^\\s]+|(?<![A-Za-z0-9_/#])(?:" + tag + ")+", "gu");
  return t.body.split(/\r?\n/).flatMap(line => {
    let prose = "", end = 0, removed = false;
    for (const match of line.matchAll(token)) {
      if (!match[0].startsWith("#")) continue;
      removed = true;
      prose += line.slice(end, match.index);
      end = match.index + match[0].length;
      if (!prose.trim() || /[ \t]$/.test(prose))
        while (end < line.length && /[ \t]/.test(line[end])) end++;
    }
    if (!removed) return [line];
    prose = (prose + line.slice(end)).trimEnd();
    return prose && !/^[\s，、,；;]+$/u.test(prose) ? [prose] : [];
  }).join("\n").trim();
}

export function validateFields(t) {
  topicNames(t);
  if (t.platform === "bilibili") {
    if(!t.declaration?.category?.trim()) throw Error("请补齐B站必填创作声明类别");
    for (const match of platformBody(t).matchAll(/(?:^|\s)#([\p{L}\p{N}_]+)(?=$|[\s#，。！？、；：,.!?;:])/gu))
      throw Error("请将清单里的话题「" + match[1] + "」加入 B站独立标签后重试");
  }
  if (t.platform === "douyin" && t.declaration == null) return;
  if (t.platform === "channels" && (typeof t.shortTitle!=="string" || !t.shortTitle.trim())) throw Error("请提供视频号短标题，完整标题将进入视频描述");
  if (["xhs","channels"].includes(t.platform) && !["原创","原创声明","声明原创"].includes(t.declaration?.value)) throw Error("请核对本次原创声明意愿");
  if (!t.declaration || typeof t.declaration.value!=="string" || !t.declaration.value.trim())
    throw Error("请根据作者意愿和当前平台控件列出原创、自制或对应声明。缺少对应入口须报告");
}
async function selected(node) {
  return node.evaluate(e=>{
    const marked=n=>n.matches('input:checked,[aria-checked="true"],[aria-selected="true"],[aria-pressed="true"]') ||
      [...n.classList].some(v=>/(?:^|[-_])(checked|selected|active)(?:$|[-_])/i.test(v) && !/unselected|unchecked|inactive|disabled/i.test(v));
    return marked(e)||[...e.querySelectorAll("input,[aria-checked],[aria-selected],[aria-pressed]")].some(marked);
  });
}
export async function declaration(page,cfg,t,spec,apply=false) {
  if(t.platform==="douyin" && t.declaration==null) return {mode:"平台默认，未操作"};
  if(t.platform==="xhs" || t.platform==="channels") return originalSwitch(page,t,apply);
  if(t.platform==="bilibili" && ["自制","内容为自制：未经作者允许，禁止转载"].includes(t.declaration?.value)) return biliDeclaration(page,t,apply);
  if(!spec?.selected) throw Error("需要声明控件及选中状态的定位");
  let opened=false;
  if(spec.open && !(await find(page,cfg,spec.selected).catch(()=>null))){
    const toggle=await find(page,cfg,spec.open);
    if(await toggle.evaluate(e=>e.matches("input[readonly], [role=combobox]"))) await toggle.click();
    else await editorAction(toggle,true,"edit");
    opened=true;
  }
  try{
    const node=await find(page,cfg,spec.selected);
    const label=spec.label ? await find(page,cfg,spec.label) : node;
    const value=displayText(await readText(label));
    if(value!==displayText(t.declaration.value)) throw Error("声明文字与清单不同");
    if(!await selected(node) && apply) await editorAction(label,true,"edit");
    if(!await selected(node)) throw Error("原创或对应声明尚未选中，请检查官网控件和可能的本人确认");
    return {selected:value};
  } finally {
    if(opened) await (await find(page,cfg,spec.open)).click();
  }
}
export async function topics(page,cfg,t,spec,verifyOnly=false) {
  const names=topicNames(t);
  if(t.platform==="channels") return bindChannelTopics(page,t,!verifyOnly);
  if(!names.length) return {bound:[]};
  if(t.platform==="xhs") return bindTopics(page,t.body,names,verifyOnly);
  if(!spec?.tokens || !Array.isArray(spec.tokens) || spec.tokens.length!==names.length)
    throw Error("按清单为各个成品话题链接或标签芯片指定定位");
  if(!verifyOnly && t.platform==="bilibili") {
    for(const [i,name] of names.entries()) {
      if(await find(page,cfg,spec.tokens[i]).catch(()=>null)) continue;
      const input=await find(page,cfg,spec.input);
      await input.fill(name);await input.press("Enter");
    }
  }
  if(!verifyOnly && t.platform==="douyin") {
    const ed=await find(page,cfg,spec.input);
    await ed.focus();
    await ed.press("ControlOrMeta+a");
    await ed.press("Backspace");
    if(displayText(await ed.innerText()) || await ed.locator("[contenteditable=false]").count()) throw Error("抖音正文未清空");
    const escapes=n=>n.replace(/[.*+?^$(){}|[\]\\]/g,"\\$&");
    const tokens=new RegExp("(#(?:"+names.slice().sort((a,b)=>b.length-a.length).map(escapes).join("|")+"))","g");
    for(const part of t.body.split(tokens)){
      if(!part)continue;
      if(part[0]==="#" && names.includes(part.slice(1))){
        await ed.pressSequentially("#");await page.keyboard.insertText(part.slice(1));
        const q=spec.choices?.[names.indexOf(part.slice(1))];
        const options=page.locator(q.css).filter({visible:true});
        await options.first().waitFor();
        if(await options.count()!==1) throw Error("联想项不唯一");
        const opt=options.first();
        if(![part,part.slice(1)].includes((await opt.innerText()).trim()))throw Error("联想项与目标话题不同");
        await opt.click();
      }else await page.keyboard.insertText(part);
    }
  }
  for(const [i,name] of names.entries()){
    const token=spec.tokens[i];
    const located=token.css?page.locator(token.css):page.getByText(token.text,{exact:true});
    await located.filter({visible:true}).first().waitFor();
    const node=await find(page,cfg,token);
    const label=(await node.innerText()).trim().replace(/^#/,"").trim();
    const structured=await node.evaluate((e,platform)=> !(platform==="bilibili" && e.closest('.ql-editor,[contenteditable=true]')) && !e.matches('[contenteditable=true],textarea,input') &&
      !!e.closest('a,[contenteditable=false],[data-topic-id],[data-entity-type],[class*=tag i],[class*=chip i],[class*=mention i],[class*=topic i]') &&
      !e.closest('[role=listbox],[role=option],[class*=suggest i],[class*=recommend i]'), t.platform);
    if(label!==name || !structured)throw Error("未核实绑定后的话题或标签："+name);
  }
  return {bound:names};
}
