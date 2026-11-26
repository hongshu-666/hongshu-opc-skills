export const platforms = {
  douyin: {
    label: "抖音",
    home: "https://creator.douyin.com/",
    edit: "https://creator.douyin.com/creator-micro/content/upload",
    list: "https://creator.douyin.com/creator-micro/content/manage",
    hosts: ["creator.douyin.com"],
    listCard: "[class^=\"video-card-\"][class*=\" video-card-new-\"]",
  },
  xhs: {
    label: "小红书",
    home: "https://creator.xiaohongshu.com/new/home",
    edit: "https://creator.xiaohongshu.com/publish/publish",
    list: "https://creator.xiaohongshu.com/new/note-manager",
    hosts: ["creator.xiaohongshu.com"],
    listCard: ".note-card",
  },
  bilibili: {
    label: "B站",
    home: "https://member.bilibili.com/platform/home",
    edit: "https://member.bilibili.com/platform/upload/video/frame",
    list: "https://member.bilibili.com/platform/upload-manager/article",
    hosts: ["member.bilibili.com", "space.bilibili.com"],
    listCard: ".article-card",
  },
  channels: {
    label: "微信视频号",
    home: "https://channels.weixin.qq.com/",
    edit: "https://channels.weixin.qq.com/platform/post/create",
    list: "https://channels.weixin.qq.com/platform/post/list",
    hosts: ["channels.weixin.qq.com"],
    listCard: ".post-feed-item",
  },
};
export function config(key) {
  if (!Object.hasOwn(platforms, key))
    throw Error("未知平台，请用 douyin、xhs、bilibili 或 channels");
  return platforms[key];
}

export const receiptDate=/20\d\d(?:年|-)\d{1,2}(?:月|-)\d{1,2}日?\s+\d{1,2}:\d{2}(?::\d{2})?/;

export function titleCards(page,platform,title) {
  return page.locator(config(platform).listCard).filter({hasText:title});
}
