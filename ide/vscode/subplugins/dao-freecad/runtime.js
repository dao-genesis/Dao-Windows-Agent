/*
 * DAO · FreeCAD 内置运行时（跨平台零安装）
 *
 * 用户只装插件，不装 FreeCAD：首次使用时按平台自动下载官方发行包并解出内置运行时。
 *   Linux   x64/arm64 : AppImage → --appimage-extract（免 FUSE、免 root）
 *   Windows x64       : conda .7z → 便携 7zr.exe 解包（免安装器、免管理员）
 *   macOS   x64/arm64 : .dmg → hdiutil attach + 拷贝 .app（免拖拽安装）
 * 所有产物落在扩展 globalStorage，删插件即删运行时，不污染系统。
 */
const https = require("https");
const cp = require("child_process");
const fs = require("fs");
const path = require("path");

const FREECAD_VERSION = "1.0.2";
const REL = `https://github.com/FreeCAD/FreeCAD/releases/download/${FREECAD_VERSION}/`;
const ASSETS = {
  "linux-x64": REL + `FreeCAD_${FREECAD_VERSION}-conda-Linux-x86_64-py311.AppImage`,
  "linux-arm64": REL + `FreeCAD_${FREECAD_VERSION}-conda-Linux-aarch64-py311.AppImage`,
  "win32-x64": REL + `FreeCAD_${FREECAD_VERSION}-conda-Windows-x86_64-py311.7z`,
  "darwin-x64": REL + `FreeCAD_${FREECAD_VERSION}-conda-macOS-x86_64-py311.dmg`,
  "darwin-arm64": REL + `FreeCAD_${FREECAD_VERSION}-conda-macOS-arm64-py311.dmg`,
};
const SEVENZR_URL = "https://www.7-zip.org/a/7zr.exe";
// GitHub 直连受限地区（实测 ETIMEDOUT）的镜像前缀回退；直连优先，失败逐个降级
const GH_MIRRORS = ["", "https://ghfast.top/", "https://gh-proxy.com/", "https://ghproxy.net/"];

function assetUrl() {
  return ASSETS[`${process.platform}-${process.arch}`] || null;
}

/** 已解出的内置运行时可执行路径（各平台），不存在返回 null */
function embeddedExe(dir) {
  const candidates =
    process.platform === "win32"
      ? [path.join(dir, "FreeCAD", "bin", "FreeCAD.exe"), path.join(dir, "FreeCAD", "bin", "freecad.exe")]
      : process.platform === "darwin"
        ? [path.join(dir, "FreeCAD.app", "Contents", "MacOS", "FreeCAD")]
        : [path.join(dir, "squashfs-root", "usr", "bin", "freecad")];
  for (const p of candidates) if (fs.existsSync(p)) return p;
  // Windows 解包后可能多一层带版本号的目录（如 FreeCAD/FreeCAD_1.0.2-conda-.../bin），浅扫两层
  if (process.platform === "win32") {
    const scan = (base, depth) => {
      let names;
      try { names = fs.readdirSync(base); } catch (e) { return null; }
      for (const exe of ["FreeCAD.exe", "freecad.exe"]) {
        const p = path.join(base, "bin", exe);
        if (fs.existsSync(p)) return p;
      }
      if (depth <= 0) return null;
      for (const name of names) {
        const found = scan(path.join(base, name), depth - 1);
        if (found) return found;
      }
      return null;
    };
    return scan(dir, 2);
  }
  return null;
}

/** 纯 Node 下载（自动跟随重定向），带进度回调 */
function download(url, dest, onProgress, depth) {
  if ((depth || 0) > 8) return Promise.reject(new Error("too many redirects"));
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    // timeout: 套接字 30s 无数据即断开——受限网络下 TCP 会被静默掐死成"永久悬挂"，必须显式超时
    const req = https.get(url, { timeout: 30000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close();
        fs.rmSync(dest, { force: true });
        return resolve(download(res.headers.location, dest, onProgress, (depth || 0) + 1));
      }
      if (res.statusCode !== 200) {
        file.close();
        fs.rmSync(dest, { force: true });
        return reject(new Error("HTTP " + res.statusCode + " for " + url));
      }
      const total = parseInt(res.headers["content-length"] || "0", 10);
      let got = 0;
      res.on("data", (c) => {
        got += c.length;
        if (onProgress && total) onProgress(got / total);
      });
      res.pipe(file);
      file.on("finish", () => file.close(resolve));
    });
    req.on("timeout", () => req.destroy(new Error("socket timeout (30s no data) for " + url)));
    req.on("error", (e) => { file.close(); fs.rmSync(dest, { force: true }); reject(e); });
  });
}

/**
 * 健壮下载：唯一临时名防并发碰撞；GitHub 资产直连失败自动降级镜像前缀，
 * 全部候选共两轮重试；若重命名时发现目标已存在（并发竞争中另一方已完成）视为成功。
 */
async function fetchTo(url, dest, onProgress) {
  if (fs.existsSync(dest)) return;
  const part = dest + ".part-" + process.pid + "-" + Math.random().toString(36).slice(2, 8);
  const candidates = /^https:\/\/github\.com\//.test(url)
    ? GH_MIRRORS.map((m) => m + url)
    : [url];
  let lastErr = null;
  for (let attempt = 1; attempt <= 2; attempt++) {
    for (const candidate of candidates) {
      try {
        await download(candidate, part, onProgress);
        try {
          fs.renameSync(part, dest);
        } catch (e) {
          fs.rmSync(part, { force: true });
          if (!fs.existsSync(dest)) throw e;
        }
        return;
      } catch (e) {
        lastErr = e;
        fs.rmSync(part, { force: true });
        if (fs.existsSync(dest)) return;
      }
    }
    if (attempt < 2) await new Promise((r) => setTimeout(r, 3000));
  }
  throw lastErr;
}

function run(bin, args, opts) {
  return new Promise((resolve, reject) => {
    const p = cp.spawn(bin, args, { stdio: "ignore", ...(opts || {}) });
    p.on("exit", (c) => (c === 0 ? resolve() : reject(new Error(`${path.basename(bin)} exit ${c}`))));
    p.on("error", reject);
  });
}

async function provisionLinux(dir, url, report) {
  const appimage = path.join(dir, "FreeCAD.AppImage");
  if (!fs.existsSync(appimage)) {
    report("下载 FreeCAD AppImage…");
    await fetchTo(url, appimage, (r) => report(`下载 AppImage ${(r * 100) | 0}%`));
  }
  fs.chmodSync(appimage, 0o755);
  report("解包运行时（免 FUSE）…");
  await run(appimage, ["--appimage-extract"], { cwd: dir });
  return embeddedExe(dir);
}

async function provisionWindows(dir, url, report) {
  const archive = path.join(dir, "FreeCAD.7z");
  const sevenzr = path.join(dir, "7zr.exe");
  if (!fs.existsSync(sevenzr)) {
    report("下载解包器 7zr…");
    await fetchTo(SEVENZR_URL, sevenzr);
  }
  if (!fs.existsSync(archive)) {
    report("下载 FreeCAD 便携包…");
    await fetchTo(url, archive, (r) => report(`下载便携包 ${(r * 100) | 0}%`));
  }
  report("解包运行时…");
  await run(sevenzr, ["x", archive, "-o" + path.join(dir, "FreeCAD"), "-y"]);
  return embeddedExe(dir);
}

async function provisionMac(dir, url, report) {
  const dmg = path.join(dir, "FreeCAD.dmg");
  if (!fs.existsSync(dmg)) {
    report("下载 FreeCAD 镜像…");
    await fetchTo(url, dmg, (r) => report(`下载镜像 ${(r * 100) | 0}%`));
  }
  const mnt = path.join(dir, "mnt");
  fs.mkdirSync(mnt, { recursive: true });
  report("挂载镜像并拷贝 .app…");
  await run("hdiutil", ["attach", dmg, "-nobrowse", "-quiet", "-mountpoint", mnt]);
  try {
    const app = fs.readdirSync(mnt).find((n) => /\.app$/.test(n));
    if (!app) throw new Error("dmg 内未找到 .app");
    await run("cp", ["-R", path.join(mnt, app), path.join(dir, "FreeCAD.app")]);
  } finally {
    await run("hdiutil", ["detach", mnt, "-quiet"]).catch(() => {});
  }
  return embeddedExe(dir);
}

/**
 * 按平台把 FreeCAD 官方发行包解为插件内置运行时。
 * @param {string} dir 落盘目录（扩展 globalStorage）
 * @param {(msg:string)=>void} report 进度回调
 * @returns {Promise<string|null>} 可执行路径
 */
async function provision(dir, report) {
  const url = assetUrl();
  if (!url) throw new Error(`暂不支持平台 ${process.platform}-${process.arch}，请手动安装 FreeCAD 并在设置中指定路径`);
  fs.mkdirSync(dir, { recursive: true });
  const done = embeddedExe(dir);
  if (done) return done;
  if (process.platform === "win32") return provisionWindows(dir, url, report);
  if (process.platform === "darwin") return provisionMac(dir, url, report);
  return provisionLinux(dir, url, report);
}

module.exports = { FREECAD_VERSION, assetUrl, embeddedExe, provision, download, fetchTo };
