# HRX 资源库 · SEO 与 AI 可见性方案

适用站点：`https://hrx-tools-g1ldzszv60x.qoder.zone/`（Qoder Sites 静态托管）
数据源：`data/shares.yaml` → 构建器：`tools/build_site.py` → 产物：`web/`

> **2026-10-31 决策记录**：不购买域名、不做 ICP 备案，站点继续托管在 Qoder Sites（域名/HTTPS/托管由平台代管）。
> 因此国内引擎（百度/搜狗/360/神马）**放弃**，主攻 **Google + Bing/IndexNow + Yandex + AI 引擎**——这几条路都不需要备案。
> 同日已落地「零风险基建」：卡片锚点与 `#slug` 深链、JSON-LD 补 `downloadUrl`/`fileSize`/`dateModified`/`featureList`/`WebSite` 实体、
> `robots.txt` 三组显式放行、`llms.txt` 生成、首页唯一 `<h1>`、sitemap `lastmod` 取真实变更日、`og:site_name`/`og:locale`/twitter 字段、
> `meta robots` 与 `theme-color`。**多页面化（P0）尚未做**，仍是全站 1 个可索引 URL。

> **2026-11-04 决策记录**：
> 1. 站点品牌统一为 **HRX 资源库**，微信公众号同步改名，页面与站外一律用这一个写法（实体一致性见 §4.3）。
> 2. **域名选定方案 C：继续留在 Qoder Sites**。国内引擎（百度/搜狗/360/神马）正式放弃，收录主攻 Google + Bing/IndexNow + Yandex + AI 引擎；
>    §五 的 A/B 两条路不再排期，§六 里依赖备案的百度/搜狗/360 提交动作一并删除。
> 3. 详情页正文来源定为**脚本自动抽取 `用户手册/*.md`**：手册七章结构完全统一（`### 4.x` 功能详解 + `## 五、常见问题` 疑问句小节），
>    已上架 4 款的手册体量为 4026 / 4346 / 5342 / 5108 汉字，足以支撑每页 800+ 汉字与 FAQPage，**不需要人工写作**。§七 第 2 条据此调整。
> 4. 分类页 `/cat/*.html` 改为**同类条目 ≥3 时才由构建器自动生成**。当前 5 条恰好分 5 类、一页一条，
>    内容与详情页雷同，属典型 doorway page，宁可不生成。§3.1 的「8 个分类页」按此修正。
> 5. 同日已落地：站点名与域名收进 `data/shares.yaml` 的 `site:` 段（缺 `url` 时构建**直接失败**，本地预览须显式 `--offline`）；
>    扫描器回写不再抹掉 `site.name` / `site.url`；新增 `tools/seo_check.py` 发布前断言。
>    此前 `--site-url` 忘传会让 canonical/og/JSON-LD/sitemap 整段消失而构建照样报成功——已发布产物确实缺这些。
>    **多页面化仍未做。**

---

## 一、现状体检

### 1.1 已达标的部分

| 项 | 实测结果 |
| --- | --- |
| 抓取可达性 | `/`、`/robots.txt`、`/sitemap.xml` 均 HTTP 200；**用 `Baiduspider/2.0`、`Googlebot/2.1` UA 请求返回正常 200**，无 CDN/WAF bot 拦截，无 `X-Robots-Tag: noindex` |
| robots.txt | `User-agent: * / Allow: /` + `Sitemap:` 声明，全放行 |
| 服务端渲染 | 卡片标题/摘要/版本/体积/分类/`<h3>` 全部预渲染进 HTML，不依赖 JS |
| 首页 meta | `title`、`description`、`canonical`、`og:type/title/description/url/image`、`twitter:card` 齐全 |
| 结构化数据 | 首页有 `ItemList` + `SoftwareApplication`（name/OS/version/offers=0） |
| 语言与编码 | `lang="zh-CN"` + UTF-8，无字体图标乱码 |
| 图片 | WebP、`loading="lazy"`、`alt` 有实质描述、`width/height` 显式声明 |
| 无外链依赖 | 无外部 JS/CSS/字体请求，首屏不存在阻塞渲染的第三方 |

### 1.2 阻塞收录的硬伤（按严重程度）

| 级别 | 问题 | 证据 | 后果 |
| --- | --- | --- | --- |
| **P0** | **整站只有 1 个可索引 URL** | `sitemap.xml` 仅 1 条 `<url>`；详情是 `<dialog>` 弹窗；`app.js` grep `hash/pushState/popstate` 全无匹配 → **连可分享的深链都不存在** | 所有长尾搜索意图（"PDF 合并 不上传 工具"、"证件照 制作 软件"）没有承接页；搜索引擎只看到首页一张脸 |
| **P0** | JSON-LD 里的 `url` 全是 `/#000_PDF超级工具箱` | `build_site.py:260` `f"{site_url}/#{e['slug']}"` | 结构化数据指向**无法独立抓取的片段地址**，`SoftwareApplication` 实体无法与 URL 绑定，等于白做 |
| **P1** | 正文内容进不了 HTML | `description`、`features` 全量只在 `<script type="application/json">` 里（`{{DATA}}`），页面上只渲染 `summary` 一句话 + 4 个短标签（`card_html` 截断到 14 字） | 单页可见文本 ~440 汉字，对"软件详情页"标准（800–1500 字）严重偏低，收录快但排名乏力 |
| **P1** | 首页无 `<h1>` | `template.html:18` 品牌名是 `<span class="wordmark">`，卡片标题才是 `<h3>` | 缺主标题信号，标题层级断裂 |
| **P1** | 内容供给仅 3 款 | 11 条数据只有 3 条挂了网盘链接，其余按"上架门槛"不渲染 | 站点规模小 → 域名级信任低 → 内链池小 |
| **P2** | 缺 AI/搜索引擎验证与提交通道 | 无 `google-site-auth`/`BingSiteAuth`/百度验证码，无 IndexNow key | 被动等爬虫，新页面发现慢 |
| **P2** | 无 `llms.txt` | `web/` 目录无该文件 | AI 检索与抓取日志分析缺一个低成本信号 |
| **P3** | 分类筛选是 `<button>` 不是 `<a>` | `chips_html()` 生成 `button data-cat` | 分类词（文档处理/证件证照…）无 URL，抓取器无法遍历，分类词零覆盖 |

### 1.3 平台层面绕不开的约束（不是代码能修的）

1. **域名是平台共享子域**：`qoder.zone` 后缀、随机片段 `-g1ldzszv60x`。
   - `update_site` 只能改前缀（`hrx-tools` → `hrx-software` 这类），**服务端强制追加随机后缀**。
   - **没有自定义域名/域名绑定字段**。这意味着：**无法完成 ICP 备案**。
2. **无备案 = 国内引擎天花板**：Google/Bing/Yandex 可正常收录；百度/搜狗/360/神马对未备案站点的收录与排名极不稳定，且国内可访问性差。
3. **资产可被平台回收**：`lifecycle`、`governance_status` 由平台控制，随机子域不可长期对外承诺。
4. **产物体积软上限 45 MB**（`build_site.py:31`），详情页增多要盯住图片。
5. **`Cache-Control: no-cache`**：`curl -I /` 响应头实测 `etag` + `cache-control: no-cache`。静态内容不做长缓存，重复抓取与 LCP 都有损耗。

**结论**：站内优化能把"可被收录"做到位；但要"被搜到"（尤其国内），必须先解决域名。

---

## 二、方案总览

| 阶段 | 内容 | 负责 | 耗时 |
| --- | --- | --- | --- |
| **P-域名** | 决策与站点搬家（备案域名 / GitHub Pages / 双轨） | **你** | 0–30 天（取决于备案） |
| **P0 多页面化** | `tools/build_site.py` 生成软件详情页 + 分类页 + `updates.html` + `404.html`；修 JSON-LD 的 `url` | 我 | 1 个工作会话 |
| **P0-bis 基建** | `llms.txt`、`meta robots`、`h1`、面包屑、IndexNow key 文件、验证 meta | 我 | 与上一步合并 |
| **P1 提交通道** | GSC / Bing WMT / 百度站长 / Yandex 验证 + sitemap 推送 + 收录 API 脚本 | 我写脚本，你注册 | 半天 |
| **P2 内容供给** | 补齐 8 款网盘链接；每款详情页正文扩到 800+ 汉字；FAQ 与版本记录 | 你为主 | 持续 |
| **P3 站外分发** | 公众号/知乎/小红书/B站/少数派 带链接发布，反向链接 | 你 | 持续 |

---

## 三、P0：多页面化（本方案的承重墙）

### 3.1 URL 结构

| 页面 | URL | title 模板 | 数量 |
| --- | --- | --- | --- |
| 首页 | `/` | `HRX 资源库 - {N} 款 Windows 离线小工具免费下载` | 1 |
| 软件详情 | `/soft/{slug}.html` | `{name}_{功能词}软件下载 v{version}_离线不上传_{category} - HRX 资源库` | N（当前 3 → 目标 11） |
| 分类 | `/cat/{cat}.html` | `{category}工具合集_{CATEGORY_NOTE} - HRX 资源库` | 8 |
| 更新记录 | `/updates.html` | `更新记录_新版本与上架时间 - HRX 资源库` | 1 |
| 关于 | `/about.html` | `关于 HRX 资源库_作者与站点说明 - HRX 资源库` | 1 |

slug 用 ASCII：`000_PDF超级工具箱` → `pdf-super-toolbox`（由 `name_en`/`exe_name` 小写连字符化）。**URL 不带中文**，避免国内引擎与部分爬虫的编码歧义。

### 3.2 详情页（最关键）

每页必须是**完整自洽的落地页**，不是弹窗的翻版。必含：

- **可见正文**（抓取即读到，不靠 JSON）：
  - `<h1>{name}</h1>` + `name_en`/`exe_name` 副标题（覆盖英文名搜索）
  - 完整 `description` 段落（现有数据已够 100+ 字）
  - `features` 全量展开（现在是 `<li>合并 PDF</li>` + 冒号后完整说明，**不截断**）
  - 下载渠道表：平台 / 链接 / 提取码 / 是否需登录 / 版本 / 体积
  - "怎么用"3–5 步（`features` 与 `dl-tip` 已给素材）
  - `keywords`/`aliases` 以自然句子出现（**"也叫 PDF工具、pdf合并、pdf拆分"**），不要堆砌成词云
  - 系统要求：Windows 10/11 64 位、离线运行、免安装解压即用
- **SEO 元素**：独立 `canonical`、`og:url`、`og:image`（该条专属封面绝对地址）、`meta robots: index,follow,max-image-preview:large`、面包屑导航
- **JSON-LD**：`SoftwareApplication` 单条实体（含 `downloadUrl`、`image`、`dateModified`）+ `BreadcrumbList` + `FAQPage`（3–5 问答，见 3.5）
- **内链**：详情页 ↔ 分类页 ↔ 相邻 3 款"同类工具"（这是抓取器发现全站的路径）

前端 `<dialog>` 详情保留不动（交互体验不变）；卡片标题 `<h3>` 包一层 `<a href="/soft/xxx.html">`。

### 3.3 首页

- 加 `<h1>`（品牌名 + 一句定位），masthead 的 `wordmark` 提升为 `<h1>`
- 分类 `<button>` 旁保留，**另加一行 `<a>` 分类链接**（抓取器只认 `<a>`）
- 卡片"详情"按钮改为 `<a href="/soft/xxx.html">详情</a>`（保留 JS 拦截做原位弹窗也行，但 href 必须真实——渐进增强）
- 修正 `head_extra()` 里 `SoftwareApplication.url` 指向真实 `/soft/{slug}.html`
- `WebSite` + `SearchAction` schema（站内搜索框可被搜索引擎识别为 sitelinks searchbox）

### 3.4 sitemap 升级

```
web/sitemap.xml            → sitemap index，引用下面三个
web/sitemap-software.xml   → N 条详情页 + lastmod（取该条 updated 字段）
web/sitemap-category.xml   → 8 条分类页
web/sitemap-page.xml       → 首页/updates/about
```

`<lastmod>` 用**条目真实 `updated`**（数据里已有，如 `data/shares.yaml:84`），不要一律写 `date.today()`——现在所有条目的 lastmod 都等于构建日，是失真信号。加 `<changefreq>`/`<priority>` 作用有限，可省。

### 3.5 FAQPage 内容（顺带喂 AI）

全站级 3–5 问，每页复用 + 每条软件专属 2–3 问：

- 「这些软件要钱吗？」→ 免费、离线、绿色免安装
- 「文件会被上传吗？」→ 本机运行、不联网
- 「支持哪些 Windows 版本？」
- 「下载后要做什么？」→ 解压即用 + 提取码说明
- 「链接失效了怎么办？」→ 公众号二维码（这条同时给转化路径）

### 3.6 顺手做掉的小项

- `lang` 已对；补 `<meta name="theme-color">`、`<link rel="alternate" type="text/plain" href="/llms.txt">`
- `app.js` 加 hash 深链：访问 `/soft/xxx.html` 不需要 JS；首页 `#slug` 打开对应详情（当前完全没有 hash 处理，是功能缺口）
- 首屏卡片图 `loading="eager" fetchpriority="high"`，其余 `lazy`
- `404.html`：实测平台对未知路径返 404 状态码，返回真实 HTML 而不是空 body，避免软 404 判定

---

## 四、P0-bis：AI 可发现性（GEO）

> 2026 年的现实：多数网站"AI 搜不到"不是因为内容差，而是 ① robots/WAF 挡了 AI 爬虫 ② 内容 JS 渲染 ③ 没有机器可读的实体描述。本站 ①② 天然达标（实测 200 + 服务端渲染），**只剩 ③ 和站外**。

### 4.1 llms.txt（新建，构建时生成）

`web/llms.txt`（UTF-8，≤10 KB）：

```markdown
# HRX 资源库
> {N} 款 Windows 离线桌面小工具，免费、绿色免安装、不联网、文件不上传。
数据更新于 {UPDATED}。

## 软件
- [PDF超级工具箱 v3.1.0](/soft/pdf-super-toolbox.html): 合并/拆分/OCR/压缩/水印，本机处理不上传
- [证照快做 v0.1.0](/soft/idphotokit.html): 本地制作标准证件照
- [AI缓存清道夫 v0.3.2](/soft/ai-cache-sweeper.html): 清理 AI 编程终端与包管理器残留缓存

## 分类
- [文档处理](/cat/doc.html) · [证件证照](/cat/idphoto.html) · ...

## 说明
- 全部为个人开发的 Windows 10/11 64 位软件，解压即用。
- 下载经夸克网盘/UC 网盘等渠道分发，提取码随链接展示。
- 联系与更新：微信公众号 HRX 资源库。
```

要点：**逐条写清"是什么 + 版本 + 干什么用 + 下载去哪"**，AI 引擎引用时可直接摘录；`> ` 引用块放站点一句话定义（llms.txt 规范的位置）；域名绝对地址一律由 `--site-url` 拼装。

**诚实预期**：公开实测中 GPTBot 抓 `llms.txt` 的次数远低于 `robots.txt`（有 12 周日志统计为 7 次 vs 3990 次），PerplexityBot 抓到过 0 次。`llms.txt` 是**低成本、非必需**的加分项，真正起作用的是 robots 放行 + 服务端渲染 + 站外被引用。不要因为做了它就以为 AI 可见性解决了。

### 4.2 robots.txt：显式放行 AI 爬虫组

```
User-agent: *
Allow: /

# 搜索引擎
User-agent: Googlebot
Allow: /
User-agent: Bingbot
Allow: /
User-agent: Baiduspider
Allow: /
User-agent: Sogou web spider
Allow: /
User-agent: 360Spider
Allow: /
User-agent: YandexBot
Allow: /

# AI 检索类（回答里带来源链接，能带回访）
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: DuckAssistBot
Allow: /

# AI 训练类
User-agent: GPTBot
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: Bytespider
Allow: /
User-agent: CCBot
Allow: /

Sitemap: {site_url}/sitemap.xml
```

两个决策点：
- **训练类要不要放行**：`GPTBot`/`ClaudeBot`/`CCBot` 决定"AI 的长期记忆里有没有你"，`OAI-SearchBot`/`PerplexityBot` 决定"实时答案里引不引你"。想被引用就都放行；不想内容进训练语料就只放行检索类。
- **robots 组按最长匹配生效**，不是"取最后一条"。所以 `User-agent: *` 的放行不会覆盖上面任何显式组——上面的写法是安全的。
- 本站无后台/接口/搜索结果 URL，**不需要任何 `Disallow`**。

### 4.3 站外：AI 能不能搜到你，主要看这个

模型语料里没有你，站内做得再细也不会被引用。按性价比排序：

1. **已有素材直接复用**：`推广素材/` 里已有 B 站封面与站点截图；`python-promo-suite` 技能能一次产出用户手册 + 8 平台推广文章 + 演示视频。**这是本项目最大的现成杠杆**。
2. **实体一致性**：`HRX 资源库` 这个品牌名在 GitHub、公众号、知乎、B 站、CSDN、下载站用**同一写法 + 同一句描述 + 同一 URL**。多源一致是 AI 认实体的核心信号。
3. **优先被爬虫站点引用的位置**：知乎"PDF 合并工具推荐"类问题回答、CSDN/掘金/博客园 的工具评测、少数派/Appinn 投稿、B 站软件介绍视频简介带链接。
4. **GitHub 仓库 + README 写站点 URL**：代码托管站在 AI 语料里权重极高，成本近乎 0。
5. **下载站/软件目录登记**（吾爱破解、小众软件目录等）：反链权重高，但要人工提交。

### 4.4 不要踩的坑

- **`qoder.zone` 平台域名被搜索引擎视为低信任共享域**：一旦平台上出现违规站，可能连累同域。这条无法通过改前缀消除。
- 网盘直链（`pan.quark.cn/s/xxx`）**不要**放进 `sitemap.xml`，也不要作为 `canonical`——那会把权重送出去。详情页才是你的页面。
- 分享链接失效会被判"页面与承诺不符"。**下架门槛已在 `load_entries()` 做了**（无链接不渲染），但已挂的链接会过期，`scan_jobs.py --check` 要定期跑。
- `noai` / `nosnippet` / `data-nosnippet` 一律别加。
- 单页内容不要为了排名堆关键词；AI 引擎对模板化填充文本会直接降权。
- 别在 `<meta name="description">` 里塞手机号/微信号，会被部分引擎当垃圾信号。

---

## 五、P-域名：需要你先定的战略问题

站内做得再好，域名不换就是"在别人地基上盖自己的楼"。三个选项：

| 方案 | 做法 | 代价 | 收益 |
| --- | --- | --- | --- |
| **A. 换自有域名（最推荐）** | 买 `xxx.com/.cn` → ICP 备案 → 静态产物部署到国内可访问的托管（或保留 Qoder Sites 做备胎，用 301/双托管） | 域名 + 备案 1–4 周、需实名 | **唯一能进百度/搜狗/360/神马的路**。同时 `llms.txt` 与品牌可信度上一个量级 |
| **B. GitHub Pages / Cloudflare Pages** | 同一份 `web/` 直接推上去，拿 `hrxsoft.github.io` 或自有域名不备案 | 免费、10 分钟 | Google/Bing/GitHub 生态收录极友好；国内访问一般 |
| **C. 留在 Qoder Sites** | 只做 P0/P0-bis | 零成本 | 天花板锁死在 Google/Bing/AI 的长尾；国内引擎基本放弃 |

**最小可行验证**（无论选哪个都要做）：`build_site.py` 的 `--site-url` 已参数化，换域名只需改构建参数重跑，`canonical`/`og`/`sitemap`/`llms.txt` 全部自动跟着走。

---

## 六、提交通道清单（P1，等 P0 落地后做）

| 平台 | 动作 | 备注 |
| --- | --- | --- |
| Google Search Console | 验证域名属性 → 提交 `sitemap.xml` → URL 检查逐个"请求编入索引" | 验证方式选 HTML 文件时，构建器要多写一个 `googleXXXX.html` |
| Bing Webmaster Tools | 可从 GSC 一键导入 → 提交 sitemap → **IndexNow**（把 `key.txt` 放 `web/`，新页面即时推送） | **对 AI 可见性性价比最高**：ChatGPT/DuckDuckGo/Copilot 都吃 Bing 索引 |
| 百度搜索资源平台 | 验证 → 站点属性 → sitemap 提交 → **主动推送 API**（`POST http://data.zz.baidu.com/urls?site=xx&token=xx`） | **需要 ICP 备案**，方案 A 才能做 |
| 搜狗 / 360 / 神马 | 各自站长平台提交 sitemap + 邀约 | 均需备案或域名所有权；权重次于百度 |
| Yandex Webmaster | 验证 + sitemap | 对中文站收录也有外溢，IndexNow 兼容 |
| AI 引擎 | 无官方"提交"入口；Perplexity 有 `WebPulse` 爬虫、ChatGPT 依赖 Bing | 走 4.3 的站外路径才是正解 |

IndexNow/百度推送都该做成 `tools/submit_search.py`：读 `sitemap.xml` 里的 URL 列表 + token 从环境变量取（**token 不入库**，`.gitignore` 已排除敏感文件的规则要补一行）。

---

## 七、内容供给（P2）

**收录的前提是被发现，排名的前提是有承接页。**

1. **先补链接数**：8 款 `share_url: ''` 的条目（`002_文件百宝箱`…`008_发票批量整理器`）挂上网盘链接。可上架数从 3 → 11，URL 总量从 1 → 约 21（11 详情 + 8 分类 + about/updates）+ 首页。**这一步的收益超过前面所有 meta 优化。**
2. **正文加厚**：每款详情页正文目标 800–1500 汉字。素材已在 `shares.yaml` 的 `description` + `features`，且各软件源目录有 `推广套件/` 与 `用户手册`（`scan_jobs.py` 就是从这里抽的），把用户手册里的"功能详解/使用步骤/常见问题"抽进详情页即可。
3. **每款补一段"它解决什么问题"**：这是搜索引擎和 AI 都最认的内容形态（痛点 → 方案 → 怎么做 → 结果）。别写成广告词。
4. **`updates.html`**：把每条 `updated` 字段渲染成时间线，给抓取器一个"这站在动"的信号。
5. **`about.html`**：作者说明、离线与安全承诺、联系方式。这是 AI 问答里"这个站是谁做的"的唯一答案来源。

---

## 八、验收标准（别只改不看）

| 阶段 | 怎么算过关 |
| --- | --- |
| P0 完成 | `web/` 下 HTML 数 ≥ 20；`sitemap.xml` 条目数 == HTML 数；每页 `canonical` 指向自己；`curl -A Googlebot` 任一详情页能看到完整正文 |
| 提交完成 | GSC 覆盖率报告"已编入索引"> 50%；`site:域名` 手动能搜到首页 + ≥ 3 个详情页 |
| AI 可见 | 在 ChatGPT（开启搜索）/Perplexity/豆包 里问"PDF 合并 离线 Windows 工具 推荐"，回答里出现站点名或链接 |
| 有流量 | GSC 展示次数 > 0 且查询词与软件名相关（说明承接页对了） |
| 抓取健康 | GSC/Bing 抓取统计无 4xx/5xx 峰值；`robots.txt` 抓取未被拦 |

建议 `scan_jobs.py --check` + `build_site.py` 之后加一步 `tools/seo_check.py`：断言 sitemap 与 HTML 文件一致、每页有唯一 `canonical`、每页 `title` ≤ 60 字且非重复、每页有 `h1`、`llms.txt` 存在且 <10 KB。失败就不让发布。

---

## 九、执行顺序（我的建议）

1. **先回答域名问题**（第五节选 A/B/C）——选错域名，后面全要重做 `canonical`/`sitemap`。
2. **我立即做 P0 + P0-bis**：`build_site.py` 多页面化（详情页/分类页/updates/about/404）、JSON-LD 的 `url` 修正、`llms.txt`、robots.txt AI 组、`sitemap` 拆分、首页 `h1` 与真实 `<a>` 内链、hash 深链。一次提交可完成，风险只在产物体积。
3. **你并行补 8 条网盘链接**（第七节第 1 条）——不依赖代码。
4. 发布后一起做 P1 提交 + 装 `tools/seo_check.py`、`tools/submit_search.py`。
5. 内容加厚（P2）随各软件的用户手册增量补，不专门排期。
6. 站外分发（4.3）接 `python-promo-suite`，把已有手册/文章/视频按平台发出去并带站点链接。
