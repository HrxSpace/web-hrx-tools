# HRX 软件库 · 网盘分享站点

本机能离线运行的 Windows 小工具目录站：卡片 + 关键词搜索 + 网盘分享链接。
内容只由一份数据文件驱动，改数据 → 构建 → 发布，三步完成。

## 目录结构

```
Z001_网盘站点/
├─ data/shares.yaml      唯一真源，人工维护（脚本只填空、不覆盖你写的内容）
├─ site/                 前端源文件：template.html / style.css / app.js（assets/ 放二维码等固定素材）
├─ tools/scan_jobs.py    扫描软件目录 → 维护 shares.yaml + 体检报告
├─ tools/build_site.py   shares.yaml → 静态站点 web/
└─ web/                  构建产物（发布目录，不要手改）
```

## 日常维护

**1. 新增软件**（把目录放进 `AI_JOB` 即可，无需登记）

```bash
python tools/scan_jobs.py          # 自动发现新条目、填空缺字段，并打印体检报告
```

脚本按目录名（`^\d{3}_`）发现软件，自动挖：商品名/英文名/版本/exe 名/发行包体积/用户向简介/封面截图/搜索关键词。

**2. 挂网盘链接**：编辑 `data/shares.yaml`，在对应条目填三个字段

```yaml
share_url: https://pan.example.com/s/xxxx
share_code: 1A2B          # 提取码，没有就留空
platform: 夸克网盘         # 显示在按钮上
```

**3. 构建 + 本地预览**

```bash
python tools/build_site.py --site-url https://你的域名    # 带域名才会生成 canonical/og/sitemap/结构化数据
python -m http.server 4173 --bind 127.0.0.1 --directory web
```

浏览器打开 <http://127.0.0.1:4173/> 确认无误后，再让 Qoder 走 Sites 发布流程。

## 字段与状态

| 字段 | 谁负责 | 说明 |
| --- | --- | --- |
| `slug` | 脚本 | 主键=目录名，别手改 |
| `name` `name_en` `exe_name` `version` | 脚本填、你可改 | 三者常不一致：`001` 目录叫证件照制作工具，商品名是证照快做，exe 是 idphotokit |
| `summary` `description` `features` `keywords` | 脚本抽取、你可改写 | 抽取来源记在 `copy_source`；全部参与搜索 |
| `category` `aliases` | 人工 | 分类筛选栏来自 `category` 去重；`aliases` 放用户可能的叫法 |
| `share_url` `share_code` `platform` | 人工 | **没填 `share_url` 的条目不会出现在页面上**，只留在数据文件里当待办 |
| `status` | 人工 | `live` 上架 / `coming_soon` 灰态「即将上架」 / `hidden` 不渲染 |
| `image` `image_kind` | 脚本 | 优先真实界面截图（`推广套件/images` > `用户手册` > `推广文章` > `演示视频` > `docs` 验收图），退到应用图标 |
| `artifact` `artifact_dir` `size_mb` | 脚本 | 你要拿去建分享的发行包路径与体积 |

**`--check`** 只体检不写文件；**`--force`** 会重新生成自动字段（`name_en/exe_name/version/artifact/size_mb/summary/description/features/keywords/image/copy_source`），**你手工改过的这几项会被覆盖**，`share_*`/`category`/`aliases`/`name`/`status` 不受影响。定稿后请不要再跑 `--force`。

## 站点行为

- 搜索：多关键词空格分隔取「与」，命中名称/英文名/exe/分类/简介/功能/关键词/别名，命中处高亮；`/` 聚焦搜索框，`Esc` 清空；无结果时给出可点的建议词。
- 卡片：16:9 封面 + 版本/体积/分类 + 一句话 + 功能短标签；`详情` 打开面板看完整简介与功能清单。
- 下载：链接新窗口打开，`复制链接` 一并带上提取码。
- 上架门槛：只有填了 `share_url` 的条目会渲染，其余留在数据文件里，页面上看不到。
- 无后端、无外部请求：数据以 JSON 内嵌页面，卡片正文预渲染进 HTML，搜索引擎可收录。
- 缺截图的条目用排版封面并标注「界面截图待补」，不放假图。
- 公众号二维码：站头右上角、搜索无结果空态、页脚三处，都在非信息区，不遮挡搜索框/分类/卡片；素材在 `site/assets/qrcode_wc.png`，构建时复制为 `web/images/wechat-qr.png`（换码只需替换该文件）。

## 待办怎么看

```bash
python tools/scan_jobs.py --check     # 不写文件，只报现状
python tools/build_site.py            # 构建后也会打印「未挂链接、暂不显示 N 条」
```

体检报告会逐条列出：缺分享链接（附要上传的 `dist/*.zip` 绝对路径）、缺真实界面截图、未打包、版本漂移、发行包名与 spec 不一致。这些都不会让页面出错，只是告诉你还差什么。

## 合规提醒

站点选了「完全公开、可被搜索引擎收录」，页面上会直接展示网盘链接与提取码。你自己的推广套件把「网盘/云盘/提取码」列为公众号、小红书等平台的 blocker 级禁用词——站点本身不受这条约束，但**把这个站点链接当作落地页往那些平台引流时，落地页内容同样会被平台审核**。建议这类页面只在私域、群聊或问答场景分发，或先确认目标平台的规则再挂链接。
