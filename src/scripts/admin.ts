import { dump, load } from "js-yaml";
import { GitHubAdmin, notesPath, repositoryUrl, resourcesPath } from "../lib/admin-github";

type Link = { label: string; href: string };
type Resource = {
  id: string;
  name: string;
  description?: string;
  links?: Link[];
  skills?: string[];
};
type Note = { filename: string; sha: string; metadata: Record<string, unknown>; body: string };

function element<T extends HTMLElement>(id: string) {
  return document.getElementById(id) as T;
}

function field(form: HTMLFormElement, name: string) {
  return form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement;
}

const loginPanel = element("admin-login");
const loginForm = element<HTMLFormElement>("admin-login-form");
const loginStatus = element("admin-login-status");
const loginButton = element<HTMLButtonElement>("admin-connect");
const tokenInput = element<HTMLInputElement>("admin-token");
const workspace = element("admin-workspace");
const workspaceFields = element<HTMLFieldSetElement>("admin-workspace-fields");
const status = element("admin-status");
const commitLink = element<HTMLAnchorElement>("admin-commit");
const resourcePicker = element<HTMLSelectElement>("admin-resource-picker");
const resourceForm = element<HTMLFormElement>("admin-resource-form");
const resourceLinks = element("admin-links");
const linkTemplate = element<HTMLTemplateElement>("admin-link-template");
const resourceDelete = element<HTMLButtonElement>("admin-delete-resource");
const notePicker = element<HTMLSelectElement>("admin-note-picker");
const noteForm = element<HTMLFormElement>("admin-note-form");

let client: GitHubAdmin | null = null;
let busy = false;
let resources: Resource[] = [];
let resourceSha = "";
let resourceId = "";
let resourceDirty = false;
let noteFiles: string[] = [];
let note: Note | null = null;
let noteDirty = false;

function showStatus(message: string, failed = false, commitSha?: string) {
  const output = client ? status : loginStatus;
  output.textContent = message;
  output.dataset.error = String(failed);
  commitLink.hidden = !commitSha;
  if (commitSha) commitLink.href = repositoryUrl + "/commit/" + commitSha;
}

async function runTask(message: string, work: () => Promise<void>) {
  if (busy) return;
  busy = true;
  loginButton.disabled = true;
  workspaceFields.disabled = true;
  showStatus(message);
  try {
    await work();
  } catch (error) {
    showStatus(error instanceof Error ? error.message : "操作失败，请稍后重试。", true);
  } finally {
    busy = false;
    loginButton.disabled = false;
    workspaceFields.disabled = false;
  }
}

function confirmDiscard(dirty: boolean) {
  return !dirty || window.confirm("放弃尚未保存的修改？");
}

function tags(value: string) {
  return [...new Set(value.split(/[,，、]/).map((tag) => tag.trim()).filter(Boolean))];
}

function addLink(link: Link = { label: "", href: "" }) {
  const row = linkTemplate.content.firstElementChild!.cloneNode(true) as HTMLElement;
  row.querySelector<HTMLInputElement>("[data-link-label]")!.value = link.label;
  row.querySelector<HTMLInputElement>("[data-link-url]")!.value = link.href;
  resourceLinks.append(row);
}

function getLinks() {
  const links: Link[] = [];
  for (const row of resourceLinks.children) {
    const label = row.querySelector<HTMLInputElement>("[data-link-label]")!.value.trim();
    const href = row.querySelector<HTMLInputElement>("[data-link-url]")!.value.trim();
    if (!label && !href) continue;
    const url = URL.canParse(href) ? new URL(href) : null;
    if (!label || !url || !["https:", "http:"].includes(url.protocol) || url.username || url.password) {
      throw new Error("每条链接都要有名称和有效的网页网址。");
    }
    links.push({ label, href });
  }
  return links;
}

function showResource(id: string) {
  const item = resources.find((resource) => resource.id === id);
  resourceId = item?.id ?? "";
  resourcePicker.replaceChildren(
    new Option("新建分组", ""),
    ...resources.map((resource) => new Option(resource.name, resource.id)),
  );
  resourcePicker.value = resourceId;
  field(resourceForm, "name").value = item?.name ?? "";
  field(resourceForm, "description").value = item?.description ?? "";
  field(resourceForm, "tags").value = item?.skills?.join(", ") ?? "";
  resourceLinks.replaceChildren();
  const links = item?.links ?? [];
  links.length ? links.forEach(addLink) : addLink();
  resourceDelete.hidden = !item;
  resourceDirty = false;
}

function parseNote(filename: string, text: string, sha: string): Note {
  const frontmatter = /^(?:\uFEFF)?---[ \t]*\r?\n([\s\S]*?)^---[ \t]*(?:\r?\n|$)/m.exec(text);
  if (frontmatter?.index !== 0) return { filename, sha, metadata: {}, body: text };
  const metadata = load(frontmatter[1]) ?? {};
  if (typeof metadata !== "object" || Array.isArray(metadata)) {
    throw new Error("这篇笔记的头部信息无法识别。");
  }
  return { filename, sha, metadata: metadata as Record<string, unknown>, body: text.slice(frontmatter[0].length) };
}

function textValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function showNote(next: Note | null) {
  note = next;
  notePicker.replaceChildren(
    new Option("新建笔记", ""),
    ...noteFiles.map((filename) => new Option(filename.slice(0, -3), filename)),
  );
  notePicker.value = note?.filename ?? "";
  const metadata = note?.metadata ?? {};
  const slug = field(noteForm, "slug");
  slug.value = note?.filename.slice(0, -3) ?? "";
  slug.readOnly = Boolean(note);
  field(noteForm, "title").value = textValue(metadata.title);
  field(noteForm, "summary").value = textValue(metadata.summary);
  field(noteForm, "date").value = metadata.date instanceof Date
    ? metadata.date.toISOString().slice(0, 10)
    : textValue(metadata.date).slice(0, 10);
  field(noteForm, "tags").value = Array.isArray(metadata.tags) ? metadata.tags.join(", ") : "";
  field(noteForm, "body").value = note?.body ?? "";
  noteDirty = false;
}

async function readDashboard(github: GitHubAdmin) {
  const [file, files] = await Promise.all([github.readFile(resourcesPath), github.listNotes()]);
  const items = JSON.parse(file.text) as Resource[];
  if (!Array.isArray(items) || items.some((item) => !item || typeof item.id !== "string" || typeof item.name !== "string")) {
    throw new Error("仓库中的资源数据格式无法识别。");
  }
  resources = items;
  resourceSha = file.sha;
  noteFiles = files;
  showResource(resources[0]?.id ?? "");
  showNote(null);
}

async function saveResources(github: GitHubAdmin, next: Resource[], id: string, message: string) {
  const serialized = JSON.stringify(next, null, 2) + "\n";
  const saved = await github.saveFile(resourcesPath, serialized, message, resourceSha);
  resources = next;
  resourceSha = saved.content.sha;
  showResource(id);
  showStatus("已提交到 GitHub，主页将自动发布。", false, saved.commit.sha);
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy) return;
  const token = tokenInput.value.trim();
  tokenInput.value = "";
  if (!/^github_pat_[a-zA-Z0-9_]+$/.test(token)) {
    showStatus("请输入 GitHub 生成的细粒度个人访问令牌。", true);
    tokenInput.focus();
    return;
  }
  void runTask("正在连接 GitHub…", async () => {
    const github = new GitHubAdmin(token);
    try {
      const username = await github.verifyOwner();
      await readDashboard(github);
      client = github;
      element("admin-account").textContent = "@" + username;
      loginPanel.hidden = true;
      workspace.hidden = false;
      showStatus("已从 GitHub 读取。");
    } catch (error) {
      github.disconnect();
      throw error;
    }
  });
});

element("admin-reload").addEventListener("click", () => {
  const github = client;
  if (!github || !confirmDiscard(resourceDirty || noteDirty)) return;
  void runTask("正在读取 GitHub…", async () => {
    await readDashboard(github);
    showStatus("已从 GitHub 重新读取。");
  });
});

element("admin-disconnect").addEventListener("click", () => {
  if (!confirmDiscard(resourceDirty || noteDirty)) return;
  client?.disconnect();
  client = null;
  resources = [];
  resourceSha = "";
  noteFiles = [];
  showResource("");
  showNote(null);
  workspace.hidden = true;
  loginPanel.hidden = false;
  showStatus("已退出。");
  tokenInput.focus();
});

const tabs = [
  { button: element("admin-resource-tab"), panel: element("admin-resource-panel") },
  { button: element("admin-note-tab"), panel: element("admin-note-panel") },
];
for (const tab of tabs) {
  tab.button.addEventListener("click", () => {
    for (const otherTab of tabs) {
      otherTab.button.setAttribute("aria-pressed", String(otherTab === tab));
      otherTab.panel.hidden = otherTab !== tab;
    }
    showStatus("");
  });
}

resourcePicker.addEventListener("change", () => {
  if (confirmDiscard(resourceDirty)) showResource(resourcePicker.value);
  else resourcePicker.value = resourceId;
});

notePicker.addEventListener("change", () => {
  const github = client;
  const filename = notePicker.value;
  notePicker.value = note?.filename ?? "";
  if (!github || !confirmDiscard(noteDirty)) return;
  if (!filename) {
    showNote(null);
    return;
  }
  void runTask("正在读取笔记…", async () => {
    const file = await github.readFile(notesPath + "/" + filename);
    showNote(parseNote(filename, file.text, file.sha));
    showStatus("");
  });
});

resourceForm.addEventListener("input", () => { resourceDirty = true; });
noteForm.addEventListener("input", () => { noteDirty = true; });

element("admin-add-link").addEventListener("click", () => {
  addLink();
  resourceDirty = true;
  resourceLinks.lastElementChild?.querySelector<HTMLInputElement>("[data-link-label]")?.focus();
});

resourceLinks.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.closest("[data-remove-link]")) return;
  target.closest("[data-link-row]")?.remove();
  resourceDirty = true;
});

resourceForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const github = client;
  if (!github) return;
  void runTask("正在保存资源…", async () => {
    const name = field(resourceForm, "name").value.trim();
    if (!name) throw new Error("请填写分组名称。");
    const existing = resources.find((resource) => resource.id === resourceId);
    const item: Resource = {
      ...existing,
      id: existing?.id ?? "resource-" + crypto.randomUUID(),
      name,
      description: field(resourceForm, "description").value.trim(),
      links: getLinks(),
      skills: tags(field(resourceForm, "tags").value),
    };
    const next = existing
      ? resources.map((resource) => resource.id === existing.id ? item : resource)
      : [...resources, item];
    await saveResources(github, next, item.id, "Update curated resources");
  });
});

resourceDelete.addEventListener("click", () => {
  const github = client;
  const item = resources.find((resource) => resource.id === resourceId);
  if (!github || !item || !window.confirm("删除「" + item.name + "」及其中的全部链接？此操作会更新公开主页。")) return;
  void runTask("正在删除资源分组…", async () => {
    const next = resources.filter((resource) => resource.id !== item.id);
    await saveResources(github, next, next[0]?.id ?? "", "Remove a curated resource group");
  });
});

noteForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const github = client;
  if (!github) return;
  void runTask("正在保存笔记…", async () => {
    const title = field(noteForm, "title").value.trim();
    const date = field(noteForm, "date").value;
    const slug = field(noteForm, "slug").value.trim();
    if (!title || !date) throw new Error("请填写笔记标题和日期。");
    if (!note && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
      throw new Error("网址名称请用小写英文字母、数字和连字符，例如 linear-algebra。");
    }
    const filename = note?.filename ?? slug + ".md";
    if (!note && noteFiles.includes(filename)) throw new Error("已经有同名笔记，请选择其他网址名称。");

    const metadata = {
      ...note?.metadata,
      title,
      date,
      summary: field(noteForm, "summary").value.trim(),
      tags: tags(field(noteForm, "tags").value),
    };
    const body = field(noteForm, "body").value;
    const text = "---\n" + dump(metadata, { lineWidth: -1, noRefs: true }) + "---\n"
      + (body && !body.endsWith("\n") ? body + "\n" : body);
    const saved = await github.saveFile(notesPath + "/" + filename, text, "Update homepage note", note?.sha);
    if (!noteFiles.includes(filename)) noteFiles = [...noteFiles, filename].sort((a, b) => a.localeCompare(b));
    showNote({ filename, sha: saved.content.sha, metadata, body });
    showStatus("已提交到 GitHub，主页将自动发布。", false, saved.commit.sha);
  });
});

window.addEventListener("beforeunload", (event) => {
  if (!resourceDirty && !noteDirty) return;
  event.preventDefault();
  event.returnValue = true;
});
