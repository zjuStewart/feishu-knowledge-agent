# Feishu Knowledge Agent

让 AI Agent 使用你的飞书知识库：整理会议和资料、按角色回答问题、自动更新目录，并在你确认后归档为可编辑文档。

## 快速开始

**准备知识库链接和共同背景文档链接（可以多个）。** 背景文档及其子文档是所有角色共有的背景，重叠部分只计算一次。把下面这段发给你的 Agent，填上自己的信息即可：

```text
请安装并配置 https://github.com/zjuStewart/feishu-knowledge-agent ，按主 Skill 的 SKILL.md 执行。
知识库：[名称与链接]
共同背景根文档：[一个或多个链接，包含各自子文档]
我的职责与关注点：[可选]
先使用本地操作模式，目录每天 [09:00，Asia/Shanghai，可修改] 更新一次，也允许手动更新。
请检查环境和飞书访问权限，查询所需 ID，安装三个 Skill 并生成独立配置；不要覆盖已有配置。
完成首次同步和带来源的问答验证，告诉我哪些功能已可用。真实归档先给出具体计划，等我确认。
登录由我完成；缺权限时告诉我需要什么、找谁处理。不要读取或索要模型 API Key。
```

**运行需要：** macOS/Linux、Python 3.9+、能读文件和执行命令的 Agent，以及本人授权的 `lark-cli`。Agent 可先检查环境，再引导你完成缺少的步骤。当前无需额外配置 OpenAI API Key，模型由宿主 Agent 或飞书提供。

## 配好后怎么用

**直接把文件拖进 Agent 对话，或发送飞书链接/文字，说“收录这份资料”。** Agent 会识别标题和类型、提取正文、登记并开始整理，无需手填表格或再发同步指令；已配置云端智能体时也可从其对话入口提交。真实归档仍需确认具体计划。

| 直接对 Agent 说 | 会做什么 |
| --- | --- |
| “立即更新目录” | 刷新文档位置，识别新增、改名、移动和不再可见的节点 |
| “同步工作知识库” | 更新目录、变化正文和共同背景，失效材料退出当前问答 |
| “从管理/内容视角回答……” | 共用事实背景，按角色偏好检索并标明来源 |
| “整理最近一次会议，给出归档计划” | 先核验实际会议日期和来源，再预览目标路径与动作 |
| “确认移动原文《会议标题》（版本1）至「知识库/目标目录」” | 核验该计划仍有效后执行，检查正文和编辑权限 |

支持智能纪要、妙记文字、上传文件及已提取的外部文字。管理、内容、趣味三个角色可分别设置关注点。最近会议检索需配置本人纪要助手会话，也可直接提供会议链接。

## 自动运行与云端

目录可每天更新，也可随时手动更新；无变化保持安静，有实质变化或需要处理时才通知。正文仅在变化时重新读取，摘要绑定来源版本，问答按需取片段。

- **本地操作：** 同步和归档需要设备与宿主在线；“本地”不代表模型离线运行。
- **飞书云端整理：** 配置处理台和事件任务后可在设备关闭时整理资料；本地目录仍需设备在线才能刷新。原生文档可部署云端对话归档入口，在同一窗口预览、确认并收到回执；当前没有统一模式切换按钮。
- **开通云端：** 向 Agent 说明“为我配置飞书云端整理”，并指定处理台链接或允许新建。部署步骤见[云端说明](skills/lark-research-workspace/references/cloud-setup.md)，配置过程不需要把模型密钥交给 Agent。

**需要在飞书智能体窗口直接归档时，把这段发给配置 Agent：**

```text
请按主 Skill 的 references/chat-archive.md，为我配置同一窗口确认后云端归档。
目标知识库：[名称与链接]；资料处理台：[已有链接，或允许新建]。
核验云端宿主真实身份；所有会话使用同一固定程序、配置、状态目录和执行锁。
先在独立测试库验证合成归档、重复确认与跨会话共享状态，再让我确认上线。
每份真实资料先展示标题、来源版本、动作和完整目标，等我在当前窗口确认后执行并返回链接。
自动会议事件仅接收整理；不要读取模型密钥。
```

需要云端宿主能执行 Python、访问飞书并持久化共享状态。安装 Skill 后仍须完成此部署，个人设备关闭和多设备场景需分别验证。详见[对话归档配置](skills/lark-research-workspace/references/chat-archive.md)。

## 团队使用

每个知识库绑定一个独立处理台，处理台放在对应知识库内，团队成员使用同一个入口。共同背景和角色配置由团队维护；个人偏好保存在每个人本地的 `state/personal-context.json`，不上传覆盖团队背景。

归档事项以“资料标题 → 知识库/目标位置”展示；内部编号只用于追踪，无需用户记忆或输入。同名资料仍须核对来源链接、版本和动作，含糊的“同意”不能自动对应多份计划。云端归档执行须单独部署和验收，接入大模型 API 本身不等于具备执行能力。

## 手动安装与更多配置

<details>
<summary>展开手动安装步骤（已让 Agent 配置的用户可跳过）</summary>

下载仓库 ZIP 或克隆仓库，将 `skills/` 下三个文件夹放进宿主 Skill 目录；Codex 可用 `~/.codex/skills/`。已有同名版本先比较或备份。用 `lark-cli --help` 确认支持 `wiki +node-list`、`docs +fetch` 等命令，并由本人完成授权。

在仓库根目录初始化，替换示例参数；个人配置与运行数据放在仓库外：

```bash
python3 skills/lark-research-workspace/scripts/init_workspace.py \
  --workspace "$HOME/workspaces/feishu-knowledge" \
  --base-url 'https://YOUR-TENANT.feishu.cn' \
  --space-id 'YOUR_SPACE_ID' \
  --space-name '我的工作知识库' \
  --shared-root 'YOUR_SHARED_ROOT_NODE_TOKEN'
```

需要多个背景入口时，重复添加 `--shared-root '另一背景节点TOKEN'`；共同背景取各入口及后代的并集，任一必需入口不可见时暂停使用当前背景。原有单入口配置仍可使用。

把生成的 `profile.json` 路径交给 Agent，并说“使用 lark-research-workspace，同步我的工作知识库”。初始化不覆盖非空目录，也不会创建定时任务。遇到 `needs_summary`，由 Agent 按 Skill 读取完整缓存并补齐摘要，不反复重跑整个同步。

</details>

[个人配置参数](skills/lark-research-workspace/references/configuration.md) · [每日同步模板](skills/lark-research-workspace/references/scheduling.md) · [详细配置提示词与权限清单](skills/lark-research-workspace/references/agent-setup-prompts.md)

## 支持范围与验证

原始流程已在 Codex + 飞书 CLI 上实测，功能代码包含目录、版本、确认门禁和团队隔离的离线测试；其他账号云端部署、Claude Code、豆包、WorkBuddy 的执行与调度需分别验证。原生 Windows 尚未支持。

超过45000字符的材料需分段处理；文字 PDF 需要 `pdftotext`，扫描件、图片、音视频及任意外部网页需额外提取。检索使用词项与片段匹配。真实事件触发、设备关机运行和真实归档应分别验收，离线测试不能替代。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 scripts/check_release.py
```

每人独立授权、独立配置与缓存。公开包只包含代码、模板和虚构测试，不含个人文档或凭据；安装不会自动授予飞书权限。

### 云端归档执行

提供 `chat_archive.py` 对话入口和单执行者程序：在当前窗口准备具体计划，本人确认后核验版本、执行原生文档归档并返回共享回执；重复确认复用回执。已在隔离合成资料上验证实际移动、正文与编辑权限、跨会话回执和锁互斥；其他账号、既有飞书聊天、物理关机和两台真实设备需分别验收。部署见[对话归档配置](skills/lark-research-workspace/references/chat-archive.md)；尚不支持多用户并发执行。
