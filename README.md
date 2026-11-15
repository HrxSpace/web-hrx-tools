# HRX 资源库

**官方网站：<https://pcpan.top>**

免费 Windows 离线小工具目录：绿色免安装、不需要联网、文件不上传。
PDF 合并拆分、证件照制作、图片去水印、AI 缓存清理等常用操作全部在自己电脑上完成，
经夸克网盘、UC 网盘等渠道分发，提取码在页面直接展示。

> 本仓库是**站点的源码与发布管线**（数据驱动的静态站点生成器），不是各软件的源码。
> 软件由个人开发者 HRX 独立开发，安装包经站点上的网盘渠道分发。

- 网盘链接失效、软件问题反馈：请提 [Issue](https://github.com/HrxSpace/web-hrx-tools/issues)
- 微信公众号：**HRX 资源库**（站点页脚有二维码，可提需求、接受定制开发）

---

以下为站点维护文档。内容只由**上架目录 `catalog/`** 驱动：改一个条目的文件夹 → 构建 → 发布，三步完成。

## 目录结构

```
Z001_网盘站点/
├─ catalog/                     上架目录：站点展示的唯一真源（一条目一个文件夹）
│  ├─ site.yaml                 站点级配置：品牌名 / 公众号名 / 域名 / 验证文件 / 常见需求导航
│  ├─ index.csv                 自动导出的总清单（只读视图，Excel 直接打开）
│  ├─ links.csv                 链接往返表（links out 产出、links in 写回）
│  └─ 000_PDF超级工具箱/         目录名 = slug，别改（改了等于换 URL）
│     ├─ meta.yaml              名称 / 版本 / 分类 / 状态 / 网盘渠道（人改这个）
│     ├─ manual.md              详情页正文（原用户手册的副本，可以直接改）
│     ├─ cover.png              卡片封面原图（构建转 webp）
│     ├─ detail.png             详情放大图（可选）
│     └─ _source.json           采集来源与 sha1（人不用动）
├─ data/paths.yaml              源工程根目录配置（只给采集与体检用，构建不读）
├─ site/                        前端源文件：template.html / style.css / app.js（assets/ 放二维码等固定素材）
├─ tools/catalog.py             catalog 维护：采集 / 体检 / 导出 / 链接 / 漂移提醒
├─ tools/build_site.py          catalog → 静态站点 web/（零外部依赖）
├─ tools/seo_check.py           发布前断言：canonical/sitemap/title/h1/JSON-LD 对齐才放行
├─ tools/submit_indexnow.py     IndexNow 即时提交（确认线上 200 后推给 Bing/Yandex 等）
├─ tools/scan_jobs.py           只读体检：AI_SOFT 下的 ^\d{3}_ 工程现状
├─ tools/scan_docs.py           只读体检：AI_WORD 下的 ^W\d{3}_ 工程现状
├─ tools/paths.py               解析/校验两个源工程根目录（采集与体检用）
└─ web/                         构建产物（pcpan.top + qoder.zone + pages.dev 共用发布源，已进版本库，不要手改）
```

## 换机器 / 目录布局不同

**构建零依赖**：封面、正文、链接都在 `catalog/<条目>/` 里，所以换机器、换盘符、在根本没有 AI_SOFT 的机器上
（比如构建机）重跑 `build_site.py`，产物逐字节一致——这条已实测：把整个工程复制到没有源工程的临时目录重建，29 个产物文件哈希全等。

源工程只在三件事上还需要：采集新条目（`catalog.py intake`）、体检（`scan_jobs.py` / `scan_docs.py`）、
漂移比对（`catalog.py drift`）。它们的根目录**不写进数据文件**（那是机器环境，跨机器会失效），
统一由 `data/paths.yaml` 以相对本站点工程的路径表达，默认 `../AI_SOFT`（软件）与 `../AI_WORD`（文档）。

```bash
python tools/paths.py show     # 打印每个根的取值、来源层与解析结果
python tools/paths.py check    # 同上，任一目录不存在时退出码 2
python tools/paths.py set --jobs-root ../AI_SOFT --docs-root ../AI_WORD   # 改团队默认
python tools/paths.py set --local --jobs-root E:/Other/AI_SOFT            # 只改本机，不进版本库
```

优先级：命令行 `--jobs-root/--docs-root` > 环境变量 `HRX_JOBS_ROOT`/`HRX_DOCS_ROOT` >
`data/paths.local.yaml`（本机例外，已被 `.gitignore` 排除）> `data/paths.yaml` > 内置默认。
源目录解析不到时采集与体检会**直接失败并告诉你取值来源**；构建不受影响（它已经不读源工程了）。


## 日常维护

**1. 新增一条**（软件或文档工程放进对应根目录后采集）

```bash
python tools/catalog.py intake 012_老照片修复工具      # 软件：拷封面+手册，自动填名称/版本/简介
python tools/catalog.py intake W001_某文档 --doc       # 资料
```

采集进来的条目一律 `status: draft`，要上架再自己改 `live` 并挂链接。
想看源工程里还有哪些没采集、版本是否漂移：`python tools/scan_jobs.py` / `python tools/scan_docs.py`（都只读）。

**2. 挂网盘链接**（三选一：命令行 / 改 meta / Excel 批量）。一个资源可以挂多个渠道，第一个是主渠道（卡片按钮直达），其余在详情里按顺序列出：

```bash
python tools/catalog.py link 009_AI缓存专清 --platform 夸克网盘 --url https://pan.quark.cn/s/xxxx --code 1A2B
python tools/catalog.py link 009_AI缓存专清 --platform UC网盘 --url https://drive.uc.cn/s/yyyy    # 追加
python tools/catalog.py links out            # 导出 catalog/links.csv（一条渠道一行）→ Excel 改 → links in
```

也可以直接编辑 `catalog/009_AI缓存专清/meta.yaml` 的 `downloads` 段：

```yaml
downloads:
  - platform: 夸克网盘
    url: https://pan.quark.cn/s/xxxx
    code: '1A2B'          # 提取码，没有就留空；引号别省，0101 会被当成数字
    note: 无需登录          # 可选，详情里显示一句说明
  - platform: 百度网盘
    url: https://pan.baidu.com/s/yyyy
    code: abcd
```

**3. 换封面 / 换正文**

```bash
# 最省事：把新截图直接覆盖成 catalog/001_证件照制作工具/cover.png
python tools/catalog.py refresh 001_证件照制作工具 --cover     # 或从源工程重取
python tools/catalog.py refresh 009_AI缓存专清 --manual        # 重取用户手册正文
python tools/catalog.py drift                                 # 源工程改了、目录没跟 → 只提示，不自动覆盖
```

封面规范：16:9、宽度 ≥1280（构建按 1280 出卡片图、1920 出详情图，统一转 webp；小于 1280 只缩放不放大）。

**4. 看一眼全站清单**

```bash
python tools/catalog.py list      # 命令行总览：状态 / 主渠道 / 封面有没有
python tools/catalog.py index     # 导出 catalog/index.csv，Excel 打开，按「状态」「主链接」筛
python tools/catalog.py check     # 体检：缺链接 / 缺封面 / 缺正文 / 重名 / URL 冲突
```

`index.csv` 是**只读视图**，手改会被下次导出覆盖；批量改链接走 `links.csv` 那张窄表（它才是往返的）。

**5. 构建 + 发布前检查 + 本地预览**

```bash
python tools/build_site.py                    # 品牌名与域名取 catalog/site.yaml
python tools/seo_check.py                     # 发布前断言：canonical/sitemap/title/h1/JSON-LD 一致性
python -m http.server 4173 --bind 127.0.0.1 --directory web
```

浏览器打开 <http://127.0.0.1:4173/> 确认无误后提交并推送（Cloudflare 自动部署），再把同一份 `web/` 发布到 Qoder 站点。

站点品牌名与正式发布域名只有一份，写在 `catalog/site.yaml` 的 `site:` 段（`name` / `wechat_name` / `url`）：
页面标题、`<h1>`、`og:site_name`、`llms.txt` 取 `name`，`canonical`/`og:url`/`sitemap`/JSON-LD 拼 `url`。
`wechat_name` 是**公众号的真名**，页面上"微信公众号 ·"与手册里"公众号「…」"都取它——公众号改名要走平台流程，
站点品牌改了它不会跟着变，写错了读者扫码就发现对不上号。**缺 `url` 或 `wechat_name` 时构建直接失败**——过去靠命令行传 `--site-url`，忘传就静默产出一个没有收录信号的裸页，
构建器自己还报"成功"。只想本地看效果、不要任何收录标签时显式加 `--offline`，这种产物 `seo_check.py` 会判不通过。

## 部署（pcpan.top 主站 + Cloudflare Pages / Qoder 镜像）

同一份 `web/` 同时发布到三个地址：

| 地址 | 角色 | 怎么更新 |
| --- | --- | --- |
| <https://pcpan.top> | 主站，canonical 指向它 | GitHub push 后 Cloudflare Pages 自动部署 |
| <https://web-hrx-tools.pages.dev> | 镜像/备份 | 同一 Pages 项目，GitHub push 自动部署 |
| <https://hrx-tools-g1ldzszv60x.qoder.zone> | 镜像 | Qoder 发布流程（把 `web/` 发布到现有站点） |

canonical、sitemap、llms.txt、JSON-LD 只认 `catalog/site.yaml` 的 `site.url`（当前是 pcpan.top）。
qoder.zone 与 pages.dev 上的页面也声明 pcpan.top 为 canonical，搜索权重集中到主站，三个地址不会互相抢排名。

构建依赖本机的 `../AI_SOFT`、`../AI_WORD`（封面与用户手册），GitHub 构建机上没有这两个目录，
所以**不在 Cloudflare 侧构建**：`web/` 已纳入版本库，Cloudflare Pages 只负责原样发布。

首次准备：

1. 在 GitHub 建一个空仓库，把本仓库推上去（可保留 Gitee 的 `origin`，另加名为 `github` 的远端）。
2. Cloudflare 控制台 → Workers & Pages → Create → Pages → Connect to Git，选该仓库。
3. 构建设置：Production branch `master`；Build command 留空；Build output directory `web`。
4. 保存并部署。项目名 `web-hrx-tools` 对应 <https://web-hrx-tools.pages.dev>。
5. Pages 项目 → Custom domains → 添加 `pcpan.top`（需要的话再加 `www.pcpan.top` 并 301 到主域名）。
   主站 canonical 用 `https://pcpan.top`。

日常更新（一次改动同步两边）：

```bash
python -m pip install -r requirements.txt   # 首次或换机器时
python tools/publish.py -m "Feat: ..."      # 构建 + SEO 断言 + 提交 + 推送 Gitee/GitHub
```

`publish.py` 只暂存 `catalog/ data/ site/ tools/ docs/ web/ README.md AGENTS.md requirements.txt`，不会把无关改动带进去。
它会检查 `web/` 是否真的有变动：没有变动时只推代码，并明确提示无需发布 Qoder。
GitHub 推送成功且 web/ 有变动时，自动等 Cloudflare 部署生效（最长 180 秒）后做 IndexNow 提交；
提交失败不影响推送，部署生效后手动重跑 `python tools/submit_indexnow.py` 即可。
有变动时，再让 Qoder 把同一份 `web/` 发布到现有站点。Qoder Sites 没有 Git 集成，这一步不能由
`git push` 代替；只推送不发布，qoder.zone 不会更新。

需要分开操作时，等价的手工命令：

```bash
python tools/build_site.py
python tools/seo_check.py                   # 不过就别发布
git add catalog/ data/ site/ tools/ docs/ web/   # web/ 是两边共用的发布源
git commit -m "Feat: ..."
git push origin master                      # Gitee 代码备份
git push github master                      # Cloudflare 自动部署
```

换域名只改 `catalog/site.yaml` 的 `site.url`，然后重建 + 跑 `seo_check.py`；canonical、sitemap、llms.txt、
JSON-LD 都从这一处拼出来。

## 爬虫与缓存

- 目标：搜索与 AI 爬虫尽量能抓，但不做高频压测。
- `robots.txt`：搜索引擎 / AI 检索 / AI 训练三组显式放行，每组带 `Crawl-delay: 1`（Google 不读它，真正限速靠 Cloudflare）；`Sitemap` 指向 `site.url`。
- `site/_headers`：构建时复制到 `web/_headers`；HTML 5 分钟、图片/favicon 1 天；CSS/JS 由 Cloudflare Pages 默认缓存约 4 小时，减少重复抓取。
- 站点是纯静态 + Cloudflare 边缘，爬虫压不垮源站；**不要开启 Bot Fight Mode / Under Attack Mode**，它们会把想放行的 AI 爬虫一起挑战掉。
- `404.html`：构建器产出、noindex、不进 sitemap。Cloudflare Pages 对未知路径默认回首页内容且状态码 200（软 404），产物里有 404.html 才会返回真 404。
- IndexNow：`site.indexnow_key` 配置（设计公开的凭据），构建器产出 `{key}.txt`；`tools/submit_indexnow.py` 先确认全部 URL 线上 200 再提交，避免把未部署/404 的页面推给引擎。`publish.py` 在 GitHub 推送后自动调用。
- 真遇到异常高频请求，再在 Cloudflare 控制台加“速率限制”规则；阈值放宽（例如每 IP 每分钟 120 次以上），避免误伤共用出口 IP 的用户。
- 换主域名后，去 Google Search Console / Bing / 百度重新验证 `pcpan.top` 并提交 `https://pcpan.top/sitemap.xml`；旧域名的验证文件不会自动验证新域名。

## 字段与状态

一个条目 = `catalog/<目录名>/` 里的四个文件。目录名就是主键（`slug`），改它等于下架旧条、新增一条，URL 也会跟着变。

| 位置 | 谁负责 | 说明 |
| --- | --- | --- |
| `site.name` `site.wechat_name` `site.url` `site.verify` | 人工 | `catalog/site.yaml` 的 `site:` 段：品牌名、公众号真名、正式发布域名、站长验证文件清单（每项 `file` + `text`，构建时原样写进产物）。改名只动 `name`，公众号名只动 `wechat_name`；**验证文件不要手工丢进 `web/`**，构建会清空该目录，验证会悄悄失效 |
| `site.baidu_analytics` | 人工 | 百度统计站点 ID（`hm.js?` 后面那串 32 位十六进制）。构建时注入所有页面 `<head>`，404 页与 `--offline` 预览不注入 |
| `site.tasks` | 人工 | 搜索框下方「常见需求」导航：`label`（用户会搜的任务词）+ `slug`（回答它的条目）。只渲染已上架条目，`seo_check.py` 会断言配了几个就渲染几个、目标页必须存在 |
| 目录名（`slug`） | 人工 | 主键，沿用源工程的 `数字_工程名`；`005` 这类重号已经合并，别再拆回来 |
| `kind` | 人工 | `soft` 软件 / `doc` 资料（`W` 开头的目录采集时自动判为 doc） |
| `name` `name_en` `exe_name` `version` | intake 填、你可改 | 三者常不一致：`001` 目录叫证件照制作工具，商品名是证照快做，exe 是 idphotokit。`name_en` 决定详情页 URL（`/soft/id-photo-kit`），改它等于换 URL |
| `summary` `description` `features` `keywords` | intake 抽取、你可改写 | 抽取来源记在 `copy_source`；全部参与搜索 |
| `category` `aliases` `tags` | 人工 | 分类筛选栏来自 `category` 去重；`aliases` 是用户可能的叫法；`tags` 是卡片上的 3~4 个可点标签，渲染成指向本条详情页的真 `<a>`，词必须是该详情页正文真回答得了的 |
| `downloads` | 人工 | 多网盘渠道列表，第一个为主渠道。提取码建议加引号（`'0101'`） |
| `cover` `detail_image` | 人工 | 相对本条目目录的文件名；`cover` 留空则卡片退成排版封面并标注「截图待补」，`detail_image` 可选 |
| `status` | 人工 | `live` 上架 / `coming_soon` 灰卡（两者都必须有渠道）/ `draft` 收着不上页 / `hidden` 完全不渲染 |
| `size_mb` `local_artifact` | intake 填 | 本机发行包路径与体积，**只给人核对，构建不读**，跨机器失效也不报错 |
| `updated` | 人工 | 进 sitemap 的 `lastmod`，只有这条真变了才改 |
| `manual.md` | 人工 | 详情页正文（原 `用户手册/*使用说明.md` 的副本）。软件条目缺这个文件时正文退成简介+功能清单，会偏薄；资料条目不需要 |
| `_source.json` | 脚本 | 采集时记的源工程、源文件与 sha1，`catalog.py drift` 据此判断源工程有没有改 |

`catalog/index.csv` 是这些字段的**只读导出**（17 列，Excel 直接打开）；`catalog/links.csv` 才是能往返的窄表（5 列，一条渠道一行）。

## 站点行为

- 搜索：多关键词空格分隔取「与」，命中名称/英文名/exe/分类/简介/功能/关键词/别名，命中处高亮；`/` 聚焦搜索框，`Esc` 清空；无结果时给出可点的建议词。
- 卡片：16:9 封面 + 版本/体积/分类/主渠道 + 一句话 + 功能短标签；`获取安装包` 直接打开主渠道，有提取码时卡片上会显示码、点击按钮顺手复制；多渠道时平台标签显示 `夸克网盘 +2` 这样的角标，其余渠道在详情里选。
- 详情：界面截图可点击放大（支持点击空白/`Esc` 关闭）；下载渠道按顺序列出，主渠道高亮并标「推荐」；提取码点一下就复制，打开链接时也会顺手复制提取码，页面底部有 toast 提示；不再提供重复的「复制完整链接」。
- 文档资料区块：与软件共用同一份搜索索引、同一套 `#slug` 深链与详情面板，也一起进分类筛选栏、`llms.txt` 和结构化数据（文档用 `CreativeWork`，软件用 `SoftwareApplication`）；卡片按钮是「获取资料」，详情里「篇章清单」替代「功能要点」。一条资料都没挂上链接时整段不渲染，搜索筛空后区块标题一并收起。
- 上架门槛：`status` 是 `live` / `coming_soon` 且至少挂了一个渠道的条目才渲染；`draft` 与 `hidden` 一律不上页。`live` 却忘了挂链接时**构建直接失败并列出是哪些条目**，不再静默消失。
- 无后端、无外部请求：数据以 JSON 内嵌页面，卡片正文与详情页正文都预渲染进 HTML，搜索引擎可收录。
  Cloudflare Pages（pcpan.top / pages.dev）原样发布静态文件，不会改写 HTML；Qoder 托管会在 `</body>` 前注入水印脚本
  （实测首页 31 KB → 线上 88 KB），且会把纯文本验证文件一起注入。Google 站长验证应针对主站 pcpan.top 做
  （HTML 文件法可直接用）；qoder.zone 镜像受注入影响，不要拿它做文件验证。
- 详情页：一条资源一个可索引 URL（软件 `/soft/{英文名}`、资料 `/doc/...`），URL 只用 ASCII 且按驼峰拆词（`PDFSuperToolbox` → `pdf-super-toolbox`）。产物文件仍是 `.html`，但 Cloudflare Pages 会把 `.html` 308 到无后缀形式，所以 canonical/sitemap/llms.txt/JSON-LD 一律声明无后缀的最终地址，站内链接保留 `.html`（本地预览与 Qoder 镜像不做该重定向）。正文构建期从 `catalog/<条目>/manual.md` 渲染（采集时已从源工程的 `用户手册/*.md` 冻结一份副本）：功能详解、使用步骤、运行环境、常见问题、注意事项逐节渲染。**正文只在 catalog 里存一份**：以前是构建期现取源手册，源工程一改、站点跟着漂，而且取不到时只 print 一句 miss。手册里的随文截图不入库，指向截图的「*图：…*」说明一并省略。
- 深链：卡片标题是真实的 `<a href="soft/xxx.html">`（抓取器与转发地址走这条）；卡片「详情」按钮仍是 `#slug` 锚点，点开是原位弹窗，体验没变。
- 抓取与收录：`robots.txt` 按「搜索引擎 / AI 检索类 / AI 训练类」三组显式放行并带 `Crawl-delay: 1`；`sitemap.xml` 逐条列出全部页面，每条 `lastmod` 用该条自己的 `updated`；`llms.txt` 是给 AI 引擎读的纯文本目录，每行指向详情页而不是首页片段；发布前用 `python tools/seo_check.py` 断言，不过就别发。
- 标题层级：首页唯一 `<h1>` 是品牌名，卡片标题为 `<h3>`；详情页唯一 `<h1>` 是资源名，章级标题 `<h2>`、手册小节 `<h3>`。
- 分类页 `/cat/*.html` **暂未生成**：同类 ≥3 条才值得做，现在 5 类各 1 条，一页一条与详情页内容雷同，是典型 doorway page。
- 缺截图的条目用排版封面并标注「界面截图待补」，不放假图。
- 公众号二维码：站头右上角、搜索无结果空态、页脚三处，都在非信息区，不遮挡搜索框/分类/卡片；素材在 `site/assets/qrcode_wc.png`，构建时复制为 `web/images/wechat-qr.png`（换码只需替换该文件）。
- 页脚有「收藏本站」提示，域名取 `site.url`，换主域名后自动跟着变。

## 待办怎么看

```bash
python tools/catalog.py check         # 全站体检：live 缺链接 / 缺封面 / 缺正文 / 重名 / URL 冲突
python tools/catalog.py list          # 16 条一张表：状态、主渠道、封面有没有
python tools/catalog.py drift         # 源工程改过、catalog 没跟上的条目
python tools/scan_jobs.py             # 软件侧只读报告：目录/商品名/版本/发行包/封面/已采集？/渠道数
python tools/scan_docs.py             # 文档侧只读报告：篇数/发布包/海报/已采集？/渠道数
python tools/build_site.py            # 构建后打印「draft/hidden N 条不上页」的清单
python tools/seo_check.py             # 发布前断言：收录信号齐不齐，不过就别发布
```

报告会逐条列出：没采集（附可直接跑的 `catalog.py intake` 命令）、缺分享链接、缺真实界面截图、未打包、版本漂移、发行包名与 spec 不一致。这些都不让页面出错，只是告诉你还差什么。两个 `scan_*.py` 只读，不再写任何数据文件。

## 合规提醒

站点选了「完全公开、可被搜索引擎收录」，页面上会直接展示网盘链接与提取码。你自己的推广套件把「网盘/云盘/提取码」列为公众号、小红书等平台的 blocker 级禁用词——站点本身不受这条约束，但**把这个站点链接当作落地页往那些平台引流时，落地页内容同样会被平台审核**。建议这类页面只在私域、群聊或问答场景分发，或先确认目标平台的规则再挂链接。
