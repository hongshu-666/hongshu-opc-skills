import {displayText} from "./page.js";

const biliOriginal = "内容为自制：未经作者允许，禁止转载";

export async function biliDeclaration(page,target,apply) {
  if (!["自制",biliOriginal].includes(target.declaration.value))
    throw Error("请核对本批B站自制声明及转载设置");
  const menu=page.getByPlaceholder("请选择符合您视频内容的创作声明");
  const category=target.declaration.category;
  if(typeof category!=="string" || !category.trim() || category===biliOriginal) throw Error("请提供B站必填创作声明类别");
  if(apply && await menu.inputValue()!==category){
    await menu.click();
    const list=page.locator(".bcc-select-option-list:visible").filter({has:page.locator(".auth-content")});
    await list.getByText(category,{exact:true}).click();
    await list.waitFor({state:"hidden"});
  }
  if(await menu.inputValue()!==category)throw Error("B站必填创作声明回读与清单不同");
  const option=page.locator(".auth-content .option-text").filter({hasText:biliOriginal});
  if (!await option.isVisible()) await menu.click();
  try {
    if (displayText(await option.innerText())!==biliOriginal) throw Error("B站自制授权文字有变化");
    const marked=()=>option.evaluate(e=>e.classList.contains("option-text-selected") && !!e.parentElement.querySelector(".icon-sprite-duihao"));
    if (apply && !await marked()) await option.click();
    if (!await marked()) throw Error("B站自制选项和勾号未核实");
    return {selected:biliOriginal,category};
  } finally {
    if (await option.isVisible()) {
      await page.getByPlaceholder("请输入稿件标题").click();
      await option.waitFor({state:"hidden"});
    }
  }
}

export async function originalSwitch(page,target,apply) {
  const xhs=target.platform==="xhs";
  const row=xhs ? page.locator(".custom-switch-card").filter({has:page.getByText("原创声明",{exact:true})}) : page.locator(".declare-original-checkbox");
  const box=row.locator(xhs ? '.custom-switch-switch input[type=checkbox]' : 'input[type=checkbox]');
  const dialog=page.locator(xhs?".d-modal:visible":".weui-desktop-dialog:visible").filter({hasText:"原创声明须知"});
  const toggle=row.locator(xhs?".custom-switch-switch .d-switch":"label.ant-checkbox-wrapper");
  if(xhs && !await toggle.isVisible()){
    if(!await page.locator(".custom-switch-card:visible").count()){
      const more=page.getByText("更多设置",{exact:true}).filter({visible:true});
      if(await more.count()===1)await more.click();
    }
    if(!await box.waitFor({state:"attached",timeout:1500}).then(()=>true,()=>false)){
      if(target.originalFromPref)return {skipped:"平台当前未开放原创声明，已按普通笔记发出"};
      throw Error("当前页面未开放原创声明开关（可能已达单日上限或账号暂未开放），请取消原创声明（图文设 original: false）后重试");
    }
  }
  if (!(await box.isChecked()) && apply && !await dialog.isVisible()) {
    if (await box.isDisabled()) {
      await row.locator(".custom-switch-switch").hover();
      const reason=await page.getByText(/视频时长小于.*暂不支持原创声明/).filter({visible:true}).allTextContents();
      throw Error(reason[0] || "官网已禁用原创开关，请查看资格提示");
    }
    await toggle.click();
    await Promise.race([dialog.waitFor({timeout:1800}),box.evaluate(e=>e.checked).then(()=>page.waitForTimeout(400))]).catch(()=>{});
  }
  if (await dialog.isVisible()) {
    if (!apply || target.declaration.acceptOriginalTerms!==true)
      throw Error("原创确认框仍打开，请本人确认本次须知和条款，再核对原创");
    const terms=await dialog.innerText();
    if (!terms.includes("原创声明须知") || (!xhs && !terms.includes("使用条款"))) throw Error("原创须知发生变化，请本人查看");
    if (!await dialog.locator('input[type=checkbox]').isChecked())
      await dialog.locator(xhs?".d-checkbox-simulator":"label.ant-checkbox-wrapper").click();
    await dialog.getByRole("button",{name:"声明原创",exact:true}).click();
    await dialog.waitFor({state:"hidden"});
  }
  if (!await box.isChecked()) throw Error("原创开关尚未选中");
  return {selected:xhs?"原创声明":"声明原创"};
}
