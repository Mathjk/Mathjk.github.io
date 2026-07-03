import resources from "./data/resources.json";
import publicProjects from "./data/public-projects.json";
import timeline from "./data/timeline.json";
import cv from "./data/cv.json";

export const siteConfig = {
  name: "收集mathのフリーレン",
  heroNameLines: ["收集math", "のフリーレン"],
  title: "Mathematics, papers, tools, and small experiments.",
  description:
    "收集mathのフリーレン的个人主页：整理数学资源、论文检索入口、AI 工具与自用效率工具。",
  accentColor: "#2563eb",
  avatar: "/avatar.jpg",
  social: {
    bilibili: "https://space.bilibili.com/393071145",
  },
  moments: {
    timeZone: "Asia/Shanghai",
    timeZoneLabel: "Shanghai",
    note: "旧主页里最有个人气味的部分：时间、纪念日、长期陪伴的计数。",
    counters: [
      {
        label: "我们恋爱了",
        startDate: "2025-06-01",
        unit: "Days",
        inclusive: true,
        tone: "love",
      },
      {
        label: "我来到这个世界",
        startDate: "2002-07-21",
        unit: "天",
        inclusive: false,
        tone: "self",
      },
      {
        label: "Baby 来到这个世界",
        startDate: "2001-10-09",
        unit: "天",
        inclusive: false,
        tone: "baby",
      },
    ],
  },
  localWorkbench: {
    bridgeUrl: "http://127.0.0.1:3939",
    note: "本地工具台通过一个只监听 127.0.0.1 的桥接服务启动本机程序、后台脚本和本地网页。",
    startCommands: [
      "Windows: start_local_app_server.bat",
      "Linux/macOS: ./start_local_app_server.sh",
    ],
  },
  aboutMe:
    "这里会从原来的个人导航页逐步迁移成更克制的个人主页。当前先保留最核心的公开信息：数学资源、论文检索入口、AI 工具和自用小工具。后续可以继续补充研究方向、项目经历、论文笔记、教育背景和联系方式。",
  skills: [
    "Mathematics",
    "Approximation Theory",
    "Paper Discovery",
    "LaTeX",
    "AI Tools",
    "Local Utilities",
  ],
  projects: resources,
  publicProjects,
  timeline,
  cv,
  notes: {
    title: "笔记",
    description: "数学、论文、工具和主页迭代的短笔记。后续可以直接新增 Markdown 文件。",
  },
  localEditor: {
    note: "本地编辑中心只在 127.0.0.1 桥接服务解锁后工作。线上发布时保持只读。",
  },
  experience: [],
  education: [],
};
