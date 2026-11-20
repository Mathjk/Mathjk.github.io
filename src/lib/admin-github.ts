export const repository = "Mathjk/Mathjk.github.io";
export const repositoryUrl = "https://github.com/" + repository;
export const tokenUrl = "https://github.com/settings/personal-access-tokens/new"
  + "?name=Mathjk+Homepage+Admin&target_name=Mathjk&contents=write";
export const resourcesPath = "src/data/resources.json";
export const notesPath = "src/content/notes";

const apiOrigin = "https://api.github.com";
const branch = "main";
const ownerId = 137137489;

type FileResponse = {
  type: "file";
  sha: string;
  encoding: string;
  content: string;
};

type FileListing = { type: string; name: string }[];

class GitHubError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export class GitHubAdmin {
  #token: string;

  constructor(token: string) {
    this.#token = token;
  }

  async verifyOwner() {
    const user = await this.request<{ id: number; login: string }>("/user");
    if (user.id !== ownerId) {
      throw new Error("请使用 Mathjk 账号生成的细粒度令牌。");
    }
    return user.login;
  }

  disconnect() {
    this.#token = "";
  }

  async readFile(path: string) {
    const file = await this.request<FileResponse>(this.contentsUrl(path) + "?ref=" + branch);
    if (file.type !== "file" || file.encoding !== "base64") {
      throw new Error("GitHub 未返回可编辑的文件内容。");
    }
    const bytes = Uint8Array.from(atob(file.content), (char) => char.charCodeAt(0));
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(bytes), sha: file.sha };
  }

  async listNotes() {
    try {
      const entries = await this.request<FileListing>(this.contentsUrl(notesPath) + "?ref=" + branch);
      return entries
        .filter((entry) => entry.type === "file" && entry.name.endsWith(".md"))
        .map((entry) => entry.name)
        .sort((a, b) => a.localeCompare(b));
    } catch (error) {
      if (error instanceof GitHubError && error.status === 404) return [];
      throw error;
    }
  }

  async saveFile(path: string, text: string, message: string, sha?: string) {
    const bytes = new TextEncoder().encode(text);
    const content = btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""));
    return await this.request<{ content: { sha: string }; commit: { sha: string } }>(
      this.contentsUrl(path),
      { method: "PUT", body: JSON.stringify({ branch, message, content, sha }) },
    );
  }

  private contentsUrl(path: string) {
    return "/repos/" + repository + "/contents/" + path.split("/").map(encodeURIComponent).join("/");
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers({
      Accept: "application/vnd.github+json",
      Authorization: "Bearer " + this.#token,
      "X-GitHub-Api-Version": "2022-11-28",
    });
    if (options.body) headers.set("Content-Type", "application/json");

    let response: Response;
    try {
      response = await fetch(apiOrigin + path, {
        ...options,
        headers,
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
        signal: AbortSignal.timeout(20_000),
      });
    } catch {
      const message = options.method === "PUT"
        ? "暂时无法确认 GitHub 是否已保存。请先到仓库核对提交，再决定是否重试。"
        : "暂时无法连接 GitHub，请稍后重试。";
      throw new Error(message);
    }

    if (response.ok) return await response.json() as T;
    const status = response.status;
    if (status === 401) throw new GitHubError(status, "令牌无效或已过期，请重新连接 GitHub。");
    if (status === 429 || response.headers.get("X-RateLimit-Remaining") === "0") {
      throw new GitHubError(status, "GitHub 暂时限制了请求频率，请稍后重试。");
    }
    if (status === 403 || status === 404) {
      throw new GitHubError(status, "GitHub 拒绝访问。请检查令牌已选择 Mathjk.github.io，并授予 Contents 读写权限。");
    }
    if (status === 409 || status === 422) {
      throw new GitHubError(status, "GitHub 未接受保存。文件可能已有更新或同名笔记已存在，请备份输入后重新读取。");
    }
    throw new GitHubError(status, "GitHub 请求失败，请稍后重试（" + status + "）。");
  }
}
