# 补丁审查流水线

[English](README.md)

> **环境要求：** Python 3.10+（推荐 3.11+ — 使用内置的 `tomllib`；3.10 需安装 `tomli` 后备库），git（仅接收方需要）

```bash
python -m pip install -r requirements-dev.txt
```

在代码仓库根目录创建 `.patch-pipeline.toml` 进行配置：

```toml
release = "bhs_pb2_35d44"
base_branch = "release/bhs_pb2_35d44"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
test_timeout_seconds = 600
```

或使用环境变量：`PATCH_PIPELINE_RELEASE=release-name`，`PATCH_PIPELINE_BASE_BRANCH=...` 等。

---

## 仓库结构

```
repo-root/
├── python/                    # Python 实现
│   ├── config.py
│   ├── utils.py
│   ├── patch_receive.py
│   ├── patch_apply.py
│   ├── patch_check.py
│   ├── patch_test.py
│   ├── patch_report.py
│   ├── patch_integrate.py
│   └── approval.py
├── bash/                      # Bash 编排（使用 Python 生成 JSON 元数据）
│   ├── patch_receive.sh
│   ├── patch_apply.sh
│   ├── patch_check.sh
│   ├── patch_test.sh
│   └── patch_integrate.sh
├── tests/
├── pyproject.toml
├── requirements-dev.txt
└── .patch-pipeline.toml       # 配置文件（可选）
```

---

## 五个步骤

### 第一步 — 接收并验证补丁

```bash
# Python
python python/patch_receive.py /mnt/shared-patches/release-name/2026-03-26/ --no-prompt
# Bash
bash bash/patch_receive.sh /mnt/shared-patches/release-name/2026-03-26/
```

验证每个 `.patch` 文件（必须为 `git format-patch` 输出），显示差异统计信息，执行静态检查，并在本地暂存补丁。只有在需要替换整个日期会话时才使用 `--force`；它会先删除旧的暂存产物，避免残留补丁被误应用。技能需要在不打开提示的情况下附加评审备注时，可使用 `--note "..."`。

### 第二步 — 应用到审查分支

```bash
python python/patch_apply.py
# 或：bash bash/patch_apply.sh
```

从已配置的基础分支创建 `review/2026-03-26/<patch-slug>` 分支，并使用 `git am --3way` 应用补丁。遇到冲突时暂停等待手动解决。

### 第三步 — 功能等价性检查 ⭐

```bash
python python/patch_check.py
# 或：bash bash/patch_check.sh
```

比较发送方*意图*（其补丁）与接收方*实际落地*内容之间的差异。由于代码库可能因重构而产生分歧，此工具按文件检查相同的逻辑变更是否存在。

- **MATCH（匹配）**（≥75%）— 相同的逻辑变更已正确落地
- **PARTIAL（部分匹配）**（40–75%）— 变更部分存在；建议逐行对比差异
- **MISMATCH（不匹配）**（<40%）— 存在显著分歧；请与发送方确认意图
- **MISSING（缺失）**— 发送方修改了此文件，但接收方未有任何变更落地
- **EXTRA（额外）**— 接收方在发送方未涉及的文件中存在变更（必须审查，不会自动通过）

只有所有文件均为 `MATCH` 时才允许集成；`PARTIAL`、`MISMATCH`、`MISSING` 和 `EXTRA` 都会产生 `NEEDS REVIEW`。

### 第四步 — 运行测试

```bash
python python/patch_test.py --no-prompt --silicon-result PENDING
# 或：bash bash/patch_test.sh --no-prompt --silicon-result PENDING
```

自动运行构建及单元测试。`--no-prompt` 可使技能或 CI 执行保持确定性；如果已有硬件结果，请使用 `--silicon-result PASS|FAIL|PENDING|SKIP` 传入。

### 第五步 — 生成报告并集成

```bash
python python/patch_report.py     # 创建 REVIEW_REPORT.md 和 REVIEW_REPORT.html
python python/patch_integrate.py --approval-file /path/to/approval.json
# 或：bash bash/patch_integrate.sh --approval-file /path/to/approval.json

集成过程为非交互且默认失败即停止。它要求补丁完整应用、`check_data.json` 中所有文件均为 `MATCH` 且没有 `EXTRA`、`test_data.json` 中没有 `FAIL`/`TIMEOUT`/`ERROR`，并要求批准 JSON 与准确的评审分支提交集合及报告 SHA-256 绑定。`PENDING`/`SKIPPED` 会保留在报告中，由范围明确的批准人决定是否可以继续。集成步骤会包含评审分支独有的全部提交，包括应用后的清理或冲突解决提交，然后创建 `integrate/<日期>/<摘要>` 分支并通过 `gh` 创建 GitHub PR。若未安装 `gh`，脚本会打印等价命令。

批准邮件只有在技能将不可变的邮件元数据导出为以下 JSON 时才可作为人工批准来源；单独的 `LGTM` 或未指明范围的 yes/no 不足以集成：

```json
{
  "decision": "APPROVED",
  "approval_type": "email",
  "message_id": "<邮件消息 ID>",
  "sender": "sender@example.com",
  "approved_at": "2026-09-15T15:00:00+08:00",
  "review_branch": "review/2026-03-26/fix-timing",
  "commit_shas": ["<评审分支完整提交 SHA>"],
  "report_file": "REVIEW_REPORT.html",
  "report_sha256": "<64 位十六进制 SHA-256>"
}
```

验证器会将验证后的记录保存为 `.patch-staging/<日期>/approval_data.json`，并将批准人及消息 ID 写入 PR 描述。
```

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| `git am` 冲突 | 修复文件，执行 `git add`，再运行 `git am --continue`。或执行 `git am --abort` 中止。 |
| Cherry-pick 冲突 | 修复文件，执行 `git add`，再运行 `git cherry-pick --continue`。或执行 `--abort` 中止。 |
| 检查时显示 MISMATCH | 查看并排差异输出，如功能等价请与发送方确认。 |
| 文件 MISSING | 检查 `git am` 日志，必要时手动重新应用。 |
| EXTRA 文件 | 必须审查——接收方修改了发送方补丁未涉及的文件。 |
| 集成被阻止 | 查看 `approval.py` 的输出；所有技术证据和准确的批准范围都必须匹配。 |
| `--force` 后仍有旧补丁 | `--force` 现在会替换整个日期会话；请重新执行接收和应用。 |

## 运行测试

```bash
python -m pytest tests/ -v
```
