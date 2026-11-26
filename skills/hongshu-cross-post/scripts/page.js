// 只使用目标平台的可见网页和浏览器文件上传能力。
export function owned(frame, cfg) {
  try {
    const url=new URL(frame.url());
    return url.protocol==="https:" && cfg.hosts.includes(url.hostname);
  } catch {
    return false;
  }
}
const frames = (page, cfg) => (cfg.home==="https://channels.weixin.qq.com/" ? [page.mainFrame()] : page.frames()).filter(f=>owned(f,cfg));
export async function find(page, cfg, q, allowHidden = false) {
  if (!q || typeof q !== "object") throw Error("需要按实际页面指定控件");
  const scope = frames(page, cfg);
  const candidates =
    q.frame === undefined ? scope : [scope[q.frame]].filter(Boolean);
  const hits = [];
  for (const f of candidates) {
    const loc = q.css ? f.locator(q.css) : f.getByText(q.text, { exact: true });
    for (const item of await loc.all())
      if (allowHidden || (await item.isVisible())) hits.push(item);
  }
  if (hits.length !== 1) {
    const error = Error("控件匹配数量 " + hits.length + "，请 inspect 后缩小定位");
    error.matchCount = hits.length;
    throw error;
  }
  return hits[0];
}
export function displayText(value) {
  return String(value).replace(/[\u200b\ufeff]/g,"").replace(/\r\n?/g,"\n").replace(/\u00a0/g," ").replace(/\s+/gu," ").trim();
}
export async function readText(node) {
  return node.evaluate(e => {
    if (e.matches("input,textarea,select")) return e.value;
    // XHS inserts a hidden [话题]# suffix into its link. Read only displayed content.
    const hidden=e.querySelectorAll(".tiptap-topic[data-topic] .content-hide");
    if(!hidden.length) return e.innerText;
    const copy=e.cloneNode(true);
    for(const suffix of copy.querySelectorAll(".tiptap-topic[data-topic] .content-hide")) suffix.remove();
    const blocks=Array.from(copy.children);
    return blocks.length && blocks.every(n=>n.tagName==="P") ? blocks.map(n=>n.textContent).join("\n") : copy.textContent;
  });
}
