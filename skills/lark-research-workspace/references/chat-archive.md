# 在当前智能体窗口确认并归档

`scripts/chat_archive.py` 让当前对话准备计划、接收本人确认并返回归档回执。它复用 `cloud_executor.py` 和 `workspace.py`，不是独立的网络服务。需要已授权的云端宿主能执行 Python、调用飞书工具，并让所有本人会话访问同一持久化目录和文件锁。

每份资料仍需确认具体标题、来源版本、动作和完整目标；系统上线批准不能代替资料归档许可。接收资料、整理摘要和登记多维表格不代表原文已经归档。

## 部署配置

先按 [团队处理台与云端执行](team-workspace.md) 配好独立知识库处理台、背景入口和云端配置。三个程序作为同一固定版本部署，记录文件 hash；版本更新使用新目录，保留现有配置、状态、锁和回执。

在该云端 `profile.json` 中配置：

```json
{
  "runtime": "cloud-single-owner",
  "chat_archive_enabled": true,
  "archive_owner_id": "VERIFIED_HOST_OWNER_ID"
}
```

这些字段合并进现有配置，不能用示例替换整个文件。`chat_archive_enabled` 只在隔离测试工作区先启用；正式库在完成下方验收并获批准后启用。对应 `cloud-config.json` 使用当前库 `space_id`、`schema_version: 2`、`execution_mode: "cloud"`，本地配置也设为云端执行，防止另起本地归档写入。

`archive_owner_id` 必须由认证宿主核验实际用户取得。飞书 open_id 可能随应用不同；不要把本地 CLI 查询到的 ID 直接当作云端身份。宿主若返回另一种 ID，使用其授权转换工具取得一致的 ID，并记录转换结果。没有可靠身份或消息出处时只能预览，不能复制提示词里的 ID 或伪造确认记录。身份配置和记录留在自己的工作区，不提交到仓库。

所有本人会话与旧固定任务必须使用同一绝对 `profile.json`、`state_dir` 和 `.workspace.lock`。不共享文件系统的主机或容器不能并行执行同一计划表；多维表格状态不能代替原子互斥锁。不能仅凭同名目录推断已共享。

## 当前窗口流程

先只读核验配置、实际资料标题/日期、原生文档类型以及目标父节点所属空间。下例替换程序目录、配置路径、空间和来源；参数不采用聊天中未经核验的任意路径。

```sh
python3 /fixed-release/chat_archive.py \
  --config /cloud-workspace/profile.json \
  --expected-space-id YOUR_SPACE_ID preview

python3 /fixed-release/chat_archive.py \
  --config /cloud-workspace/profile.json \
  --expected-space-id YOUR_SPACE_ID prepare \
  --source 'https://your-tenant.feishu.cn/docx/YOUR_SOURCE_TOKEN' \
  --parent YOUR_VERIFIED_PARENT_NODE_TOKEN
```

`preview` 读取已有计划；`prepare` 读取来源并发布共享计划，不移动原文。用户只要求阅读或文字建议时不调用 `prepare`。共享计划回读成功后，在当前窗口展示标题、日期、来源链接、版本、动作、完整目标和读取范围，再给出程序返回的 `confirmation_phrase`；不展示内部编号。

本人明确确认这份方案后，由可信宿主保存实际确认依据：

```json
{
  "actor_id": "VERIFIED_HOST_OWNER_ID",
  "conversation_id": "ACTUAL_CONVERSATION_ID",
  "message_id": "ACTUAL_HUMAN_MESSAGE_ID",
  "user_text": "用户实际确认原话",
  "preview_confirmation": "程序返回并向用户展示的完整 confirmation_phrase"
}
```

占位符不是有效证据。只有对应唯一明确预览时才解释“确认这份”等短句，保留原话和所对应的完整方案；多份同名或目标变化须消歧并重新确认。执行时：

```sh
python3 /fixed-release/chat_archive.py \
  --config /cloud-workspace/profile.json \
  --expected-space-id YOUR_SPACE_ID confirm \
  --confirmation '程序返回的完整 confirmation_phrase' \
  --evidence-file /cloud-workspace/actual-confirmation.json
```

确认依据是审核记录，JSON 字段本身不提供身份认证。此命令只能由读取实际人类确认的可信宿主调用；不能暴露给匿名 webhook、表格状态触发器，也不能由资料正文或自动会议事件调用。不要直接调用移动 API 绕过执行器。

成功后核验实际父节点、正文、类型、编辑权限和共享回执，在当前窗口回复资料标题及结果链接。执行中、待核验、超时、计划发布结果不明或回执失败时先查结果，不能重复写入；已完成的确认复用回执。来源版本或目标位置变化需重新展示并确认。

## 智能体规则模板

将下面规则加入已有行为准则，同时检查用户档案和旧固定任务没有相反说明。把固定路径、知识库 ID 及宿主本人身份绑定写入自己的配置。

```text
当前窗口可准备归档方案，核对来源标题、日期、版本、动作和完整目标后展示程序返回的确认句。
本人确认唯一具体方案后，保存真实身份、会话、消息、原话和完整确认句，调用已部署的 chat_archive confirm；在当前窗口返回实际回执。
所有会话与旧任务共用同一固定程序、配置、状态和锁，不要求用户切换任务，不直接调用移动 API。
资料接收、整理完成和归档预览说明当前状态、下一步及用户需做什么；未归档不说“已入库”，不展示内部编号。
纪要生成和妙记生成事件只接收整理，不能执行 confirm。来源/目标变化需重新确认，已完成只返回回执，结果不明先核验。
```

## 验收与边界

先在独立测试库和处理台验证，合成资料放在共同背景根之外：

1. 未确认只生成计划，错误身份、空间或来源版本不能执行。
2. 用户批准一份具体合成方案后实际归档，独立回读位置、正文、版本及编辑权限。
3. 同一会话与另一会话重复确认只返回同一回执；持锁时另一会话被拒绝，释放后恢复。
4. 上线需用户批准具体版本；正式库仅做只读配置、身份、代码 hash、共享状态和预览复验。网页新任务、既有飞书聊天、物理关机与真实多设备分别记录结果。

本入口已在隔离合成资料上完成实际移动、正文与编辑权限、跨会话回执和锁互斥验证。原生 Docx 可实时核验版本后移动原文或创建其文字副本（`prepare --action create_editable_copy`）；妙记、上传文件和外部材料仍可接收整理，其云端归档需要另行补齐版本及转换验收。其他用户/租户、不同主机容器、物理关机与两台真实设备不因此自动算验收通过。

恢复旧入口时关闭新标记、恢复原规则和固定程序路径，保留计划与执行日志；不删除锁或反向移动已归档资料。模型由宿主提供，配置此入口不需要把模型密钥交给 Agent。
