# 配置自己的飞书云端处理台

本步骤新建多维表格和工作流。先呈现目标账号、表结构、模型处理内容与推送对象；已有明确创建授权则继续，不重复询问。不要修改未指定的旧表或共享权限。优先使用已安装的 lark-base；命令参数以当前CLI的 --help 和 schema 为准。

## 表与配置

完整字段定义：[cloud-table-schemas.json](../assets/cloud-table-schemas.json)。四张表是资料收件箱、共享上下文、用户与角色、归档计划。名称用于脚本定位，不随意改名。通过 `base +base-create` 创建处理台和首张表，`base +table-create` 创建其他表。每步保存返回ID；超时或结果不确定先回读，不盲目重建。

在共享上下文创建唯一“名称=共享上下文包”的记录，初始“状态=待刷新”、摘要留空；核验后才设有效。用户与角色表添加本人用户背景及管理、内容、趣味配置，类型为用户背景/角色偏好、启用为真。

保存工作区 `cloud-config.json`，仅含本人资源标识：

```json
{
  "base_token": "YOUR_BASE_TOKEN",
  "tables": {
    "资料收件箱": "YOUR_INBOX_TABLE_ID",
    "共享上下文": "YOUR_CONTEXT_TABLE_ID",
    "用户与角色": "YOUR_ROLES_TABLE_ID",
    "归档计划": "YOUR_PLANS_TABLE_ID"
  },
  "seed_records": {"shared_bundle": "YOUR_SHARED_BUNDLE_RECORD_ID"}
}
```

base_token 是表格资源标识，不是访问凭据。登录由CLI管理，不复制认证文件。

## 表内工作流

三个 `.workflow.json` 模板使用字段名占位符，不能原样上传。通过 `base +field-list` 读取自己四张表全部字段，整理成本地 field-map.json，结构为“表名 → 字段名 → 字段ID”：

```json
{"资料收件箱":{"正文":"fldExampleBody","来源版本":"fldExampleVersion"}}
```

上面只展示结构；实际需要四张表的完整映射。运行主Skill脚本：

```bash
python3 scripts/render_workflows.py \
  --field-map /个人工作目录/field-map.json \
  --output-dir /个人工作目录/generated-workflows
```

脚本离线生成完整配置，检查字段ID，每份文件保存独立client_token，不创建或启用远端工作流。用 `base +workflow-create` 安装三份文件，保存工作流ID后按用户意图启用。不要把JSON插值为可执行shell文本，使用结构化参数或安全参数数组。结果不确定时保留原client_token并先回读。

| 模板 | 行为 |
| --- | --- |
| summary.workflow.json | 先查有效背景和启用角色，再标记处理中；同来源、正文、版本及背景复用，否则一次总结多个视角 |
| input-invalidation.workflow.json | 正文、标题、来源版本变化时清空旧摘要并重新整理 |
| role-invalidation.workflow.json | 用户背景或角色偏好变化时更新背景版本，后续资料不复用旧偏好摘要 |

慢结果写回前按来源正文、标题、版本和处理中状态重新筛选。这不是完整并发队列；背景/偏好在模型运行中变化或部分流程失败需要回读与补偿。背景恢复有效后检查等待材料是否重新触发，不自动反复重置所有记录。

## 云端伙伴与事件

使用 [云端任务模板](cloud-agent.md)，替换知识库、根文档与处理台参数。配置“会议纪要生成”和“妙记生成”事件，直接绑定事件来源。推送只给用户明确选择的对象，未授权时不向他人推送。

云端任务接收原文并维护背景；表内流程统一总结。知识库归档由具体计划确认后另行执行。平台能力与权限现场核验，模板存在不等于已部署。

## 验收

1. daily-sync 核对背景范围；长文摘要完成后 sync-context。
2. 提交虚构短材料，回读记录、摘要、来源和版本。
3. 重复同版材料验证复用；修改虚构正文验证旧摘要失效。
4. 修改虚构角色配置核对版本，测试材料标记“测试完成”。
5. 等待真实新会议事件核对唯一来源、记录和推送；手动回放不能代替事件验收。

不为测试删改真实知识库。关机运行单独验收；云端处理不会在设备关闭时更新本地缓存。
