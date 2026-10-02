---
name: lark-wiki-directory
description: "刷新飞书知识库的本地目录，支持手动更新、每日自动更新和每位用户独立配置。当用户说更新目录、同步知识库目录、立即更新科研生态目录，或要求设置目录更新频率时使用。只读取标题、层级和定位信息，不处理正文或归档迁移。"
metadata:
  version: "1.0.0"
  requires:
    bins: ["python3", "lark-cli"]
---

# 飞书知识库目录同步

用同一个确定性脚本完成手动与定时刷新。目录遍历不调用大模型，不需要任何模型 API Key。宿主 Agent 的对话与定时唤醒仍可能产生模型用量。

## 手动更新

1. 优先采用用户指定的配置；否则使用 `~/.config/lark-wiki-directory/profile.json`。只读取这一份配置及其明确指向的目录设置，不搜索凭据文件。配置中不得保存模型 Key、飞书 Token 或其他密钥。
2. 检查配置的知识库和输出位置符合任务；项目 `sources/` 及同步来源文件只读。确定后执行一次：

   ```bash
   python3 <本 Skill 目录>/scripts/refresh_directory.py
   ```

   指定另一个知识库或用户配置时：

   ```bash
   python3 <本 Skill 目录>/scripts/refresh_directory.py --config /绝对路径/profile.json
   ```

3. 检查输出 JSON 和退出码。成功后读取输出目录的 `sync-status.json`，按节点数、变化和最后成功时间简短汇报；不凭文件存在认定刷新成功。`skipped=already_running` 表示已有同步执行中，不重复启动。

只遍历当前 `lark-cli` 已授权的 **user** 身份可见节点，全量处理分页和子目录。生成 `工作知识库目录.md`、`knowledge-map.json`、`sync-status.json`；`.refresh.lock` 用于阻止并发重复刷新。共同背景根节点及后代带标记，但 `content_read=false`：目录不是正文上下文。

新增、改名、移动和移出可见目录按稳定节点ID比较。完整遍历后若共同背景根节点不再可见，仍保存新目录，并设置 `shared_context_root_visible=false`、`needs_user_action=true`；不能沿用旧目录假装根节点还在，也不能把不可见直接断言成删除。涉及正文上下文同步、知识库变更或删减时使用 `lark-research-workspace`，由其撤销旧背景与失效来源。

遇到认证、访问或读取不完整时保留上次成功目录，只简短说明需要用户处理的动作；不自行重新授权，不在定时任务内反复重试，不修改飞书文档或权限。若宿主沙箱限制访问系统钥匙串，使用宿主正规的命令授权机制；不要改为明文存储凭据。认证配置操作另用已安装的 `lark-shared` 技能。

## 每日自动更新

用户要求启用或修改周期时，使用宿主的自动化工具建立或更新任务。已有同一配置的任务就更新原任务，不另建重复任务。默认每天一次；用户另有要求时以其要求为准。Skill 自身不会常驻运行。

定时任务要明确本 Skill 的绝对路径、配置文件绝对路径和本次只运行一次的约束，并检查状态输出。目录没有实质变化时保持安静；有变化、失败或需要用户动作时简短通知。遵守项目 `AGENTS.md`；只更新配置指定的本地索引和同步状态，不触碰正文或密钥。

Codex 本地定时执行需要设备和 Codex 可用，不能宣称关机时本地文件仍更新。其他 Agent 的定时功能需由其宿主提供；没有调度工具时仍可使用手动入口，不声称已启用定时任务。

## 给另一位用户配置

环境：Python 3.9+、macOS/Linux、可运行且已用该用户本人身份授权的 `lark-cli`。需要 `wiki:node:read` / `wiki:node:retrieve` 对应读取能力及具体知识库可见权限。未验证的系统和 Agent 不宣称兼容成功。

复制 [配置示例](assets/profile.example.json) 到其 `~/.config/lark-wiki-directory/profile.json`，填写知识库名称、空间 ID、飞书域名、共同背景根节点、个人本地输出目录。共享 Skill 包，不共享他人的配置、索引或访问身份。CLI 登录由用户单独完成。

已有项目配置时，也可用不含凭据的指针配置，避免重复维护知识库参数：

```json
{
  "settings_path": "/绝对路径/项目/settings.json",
  "output_dir": "/绝对路径/项目/目录输出"
}
```

相对路径以配置文件所在目录为基准；未指定输出目录时写到知识库设置文件所在目录。配置完成后先手动验收一次，再启用该用户自己的每日任务。不同人的任务不能共用同一个输出目录。

安装时将整个 `lark-wiki-directory` 文件夹放入宿主支持的 Skill 目录。Codex 使用 `~/.codex/skills/`；Claude Code、豆包、WorkBuddy 的发现、工具执行和调度能力分别验收。脚本与配置不绑定具体模型厂商。
