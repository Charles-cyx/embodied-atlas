# 具身经纬 · Embodied Atlas

追踪自动驾驶、机器人与多地面无人车协同控制。主题覆盖视觉语言动作模型（VLA）、世界动作模型（WAM）、世界模型（WM）和多智能体协同控制。站点提供最新论文、经典文献、获奖选读、阅读路线、数据集与仿真资源。最新论文支持搜索、筛选和浏览器本地收藏。

## 本地预览

用浏览器打开 `site/index.html` 查看仓库自带的数据。要刷新预览数据，在仓库根目录运行 `python scripts/update_papers.py`，然后刷新网页。脚本使用 Python 标准库，需要能访问 arXiv API 和 Crossref REST API。

## 发布到 GitHub Pages

1. 创建 GitHub 仓库 `embodied-atlas`，把解压后的文件和目录直接放到仓库根目录，包括 `.github/`。发布后的默认地址是 `https://<用户名>.github.io/embodied-atlas/`。若使用账号根网址 `https://<用户名>.github.io`，仓库须命名为 `<用户名>.github.io`。
2. 在仓库的 **Settings → Pages → Build and deployment** 中，将 **Source** 设为 **GitHub Actions**。
3. 在 **Actions → 更新论文并发布** 中选择 **Run workflow**，选择默认分支并运行。成功后，部署任务会显示站点地址。

工作流每天按北京时间 13:17 调度。推送到仓库默认分支或在默认分支手动运行工作流也会触发更新。GitHub 的定时任务可能延迟，公开仓库连续 60 天没有活动时会停用定时任务，可在 **Actions** 重新启用。 [GitHub Pages 发布文档](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) · [GitHub Actions 定时文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

抓取失败时，之前发布的网页仍可访问。如需重试，请选择 **Run workflow**，重新抓取后再发布。

## 数据和筛选

脚本分别检索近 90 天的 arXiv 预印本和近一年内的 Crossref 会刊候选记录，通过 DOI 或规范化标题合并同一论文。列表使用正式发表日期或 arXiv 首次提交日期排序，日期保留来源提供的精度。关键词与方向标签可能遗漏采用其他术语的论文。 [arXiv API 文档](https://info.arxiv.org/help/api/user-manual.html) · [Crossref REST API 文档](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)

重点会刊按研究方向及已核实的会刊名称或 ISSN 标注，名单在 `scripts/crossref.py`。奖项根据官方获奖名单人工整理，徽标链接到获奖证据。经典论文的会刊、年份和奖项可能来自正式论文集、出版社或学会。

领域概览、经典论文、阅读路线及评测资源可在 `site/index.html` 中编辑。两个专题长文分别位于 `site/world-action.html` 和 `site/cooperative.html`，包含可跳转目录、方法流程、对照表与原始论文链接。最新论文列表由更新脚本生成。
