# 个人配置

需要 Python 3.9+、macOS/Linux、本人 user 身份授权的 `lark-cli`。按实际操作核验知识库、文档、妙记、消息、多维表格的读取/写入能力；接口权限与资源可见权限分别核验。使用已安装的 `lark-shared` 查看身份和实际缺失权限；没有该 Skill 时通过 `lark-cli auth --help` 查入口，不自动扩大授权。

三个 Skill 安装在同一个父目录。运行主 Skill 的 `scripts/init_workspace.py`：

```bash
python3 scripts/init_workspace.py \
  --workspace '/个人工作目录/feishu-knowledge' \
  --base-url 'https://YOUR-TENANT.feishu.cn' \
  --space-id 'YOUR_SPACE_ID' \
  --space-name '我的工作知识库' \
  --shared-root 'YOUR_ROOT_NODE_TOKEN'
```

初始化只写本地新目录，不联网、不读凭据、不覆盖已有配置。数据目录放仓库外。`profile.json` 中保存以下绝对路径：

```json
{
  "state_dir": "/个人工作目录/state",
  "settings": "/个人工作目录/settings.json",
  "directory": "/个人工作目录/directory/knowledge-map.json",
  "cloud_config": "/个人工作目录/cloud-config.json",
  "directory_refresh_script": "/技能安装位置/lark-wiki-directory/scripts/refresh_directory.py",
  "directory_refresh_config": "/个人工作目录/directory-profile.json",
  "cli": "lark-cli"
}
```

`directory_refresh_config` 确保日常同步及归档后的刷新使用同一位用户的配置。移动安装位置后更新 `directory_refresh_script`。`settings.json` 保存 `base_url`、`space_name`、`space_id` 和背景入口。

多个共同背景入口可重复传入 `--shared-root`，初始化会保存 `shared_context_roots` 数组及兼容旧版的首个 `shared_context_root`。脚本优先使用数组；只有旧字段的配置仍有效。背景取全部入口及后代的并集，重叠文档去重；任一必需入口不可见时暂停当前背景，恢复访问或由用户调整入口后再同步。不要为了支持多个入口而移动知识库文档。

`state/roles.json` 保存用户背景及管理、内容、趣味偏好。三个角色键名固定，内容可改；增加其他角色还需调整脚本参数校验及检索偏好。没有 `cloud-config.json` 时为本地模式：`pull-cloud` 和 `receive-cloud` 不联网，背景保存在本地；`publish` 和 `publish-plan` 需要云端配置。配置云端后以“用户与角色”表的启用项为准，见 [云端部署](cloud-setup.md)。

## 最近纪要

本人助手私聊ID与机器人ID可在初始化时一起通过 `--chat-id` 和 `--sender-id` 提供，生成 `meeting-profile.json`；已有工作区按辅助Skill示例单独创建。然后：

```bash
python3 /技能安装位置/lark-meeting-source-check/scripts/prepare_latest.py \
  --config /个人工作目录/meeting-profile.json
```

显式会议链接不需要扫描通知；真实事件任务直接绑定来源。当前解析面向中文飞书智能纪要，默认时区 Asia/Shanghai，其他语言/时区须先适配。

## 宿主与密钥

每人独立授权和工作目录，不共享 state。Codex 原始流程已实测；其他 Agent 先验证命令执行、Skill读取、目录同步和无确认阻止归档，再验证调度。没有命令执行能力时只能使用已经配置的云端入口。脚本使用 fcntl，不宣称原生 Windows 支持。

当前无需模型密钥。未来更换外部API时，只让用户在部署平台的专用密钥界面亲自填写，不让用户发到聊天，也不读取设置值。
