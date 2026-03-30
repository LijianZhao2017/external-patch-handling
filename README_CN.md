# 补丁审查流水线

[English](README.md)

> **环境要求：** Python 3.11+，git（仅接收方需要）

```bash
python -m pip install -r requirements-dev.txt
```

在代码仓库根目录创建 `.patch-pipeline.toml` 进行配置：

```toml
release = "bhs_pb2_35d44"
base_branch = "release/bhs_pb2_35d44"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
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
│   └── patch_integrate.py
├── bash/                      # Bash 实现（零依赖）
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
python python/patch_receive.py /mnt/shared-patches/release-name/2026-03-26/
# Bash
bash bash/patch_receive.sh /mnt/shared-patches/release-name/2026-03-26/
```

验证每个 `.patch` 文件（必须为 `git format-patch` 输出），显示差异统计信息，执行静态检查，并在本地暂存补丁。

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
- **EXTRA（额外）**— 接收方在发送方未涉及的文件中存在变更（属正常适配）

### 第四步 — 运行测试

```bash
python python/patch_test.py
# 或：bash bash/patch_test.sh
```

自动运行构建及单元测试，并提示输入硅测试结果（PASS/FAIL/PENDING）。

### 第五步 — 生成报告并集成

```bash
python python/patch_report.py     # 创建 REVIEW_REPORT.md
python python/patch_integrate.py  # 发送方确认 LGTM 后执行
# 或：bash bash/patch_integrate.sh
```

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| `git am` 冲突 | 修复文件，执行 `git add`，再运行 `git am --continue`。或执行 `git am --abort` 中止。 |
| Cherry-pick 冲突 | 修复文件，执行 `git add`，再运行 `git cherry-pick --continue`。或执行 `--abort` 中止。 |
| 检查时显示 MISMATCH | 查看并排差异输出，如功能等价请与发送方确认。 |
| 文件 MISSING | 检查 `git am` 日志，必要时手动重新应用。 |
| EXTRA 文件 | 通常无需处理——接收方对上下文行进行了适配。请验证是否存在意外变更。 |

## 运行测试

```bash
python -m pytest tests/ -v
```
