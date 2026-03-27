# 补丁评审管道 — 单页流程指南

## 快速开始

> **要求：** Python 3.11+，git（接收方需要）

通过在仓库根目录创建 `.patch-pipeline.toml` 来配置你的仓库：

```toml
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
```

或使用环境变量：`PATCH_PIPELINE_RELEASE=BHS-B0` 等。

---

## 5个步骤

### 步骤1 — 接收和评审补丁
```bash
python patch_receive.py /mnt/sharepoint/BHS-B0/2026-03-26/
```
验证每个 `.patch` 文件（必须是 `git format-patch` 输出），显示diff统计和受影响的文件，运行静态检查，在本地暂存补丁。

### 步骤2 — 应用到评审分支
```bash
python patch_apply.py
```
创建 `review/2026-03-26/<patch-slug>` 分支并用 `git am --3way` 应用补丁。冲突时暂停以供手动解决。

### 步骤3 — 函数式等价性检查 ⭐
```bash
python patch_check.py
```
**关键步骤。** 比较发送者*意图*（他们的补丁）与接收方*实际到达*的内容（`git diff main..review-branch`）。由于代码库通过重构而分散，行号和上下文不同 — 此工具检查相同的逻辑更改（每个文件的添加/删除内容）是否存在。

- **MATCH**（≥75%相似度） — 相同逻辑更改正确到达
- **PARTIAL**（40–75%） — 更改部分存在；审查并排比较diff
- **MISMATCH**（<40%） — 显著分散；与发送者确认意图
- **MISSING** — 发送者触及此文件，但接收方端没有内容到达
- **EXTRA** — 接收方在发送者没有触及的文件中有更改（适配）

### 步骤4 — 运行测试
```bash
python patch_test.py
```
自动运行构建检查+单元测试。提示输入硅测试结果（PASS/FAIL/PENDING）。

### 步骤5 — 生成报告和集成
```bash
python patch_report.py          # 创建 REVIEW_REPORT.md
# → 上传报告到SharePoint，发送给发送者以获取批准
python patch_integrate.py       # 在发送者说 LGTM 后
```
报告包括：补丁表、等价性检查结果、测试结果、LGTM复选框。集成在确认发送者批准后从评审分支到工作分支进行樱桃选择。

---

## 流程图

```
发送者                        SHAREPOINT                      接收者
──────                        ──────────                      ────────
git format-patch           →  /BHS-B0/2026-03-26/         ←  1. patch_receive.py
                                   *.patch                         │
                                                              2. patch_apply.py
                                                                (review/<date>/... 分支)
                                                                   │
                                                              3. patch_check.py ⭐
                                                                (发送者意图 vs 实际diff)
                                                                   │
                                                              4. patch_test.py
                                                                (构建 + 单元 + 硅)
                                                                   │
                                                              5. patch_report.py
                             ←  REVIEW_REPORT.md           ←      │
                                                                   │
发送者："LGTM ✅"                                                   │
                                                              5. patch_integrate.py
                                                                (樱桃选择 → main)
                                                                   │
                                                              构建和发布
```

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| `git am` 冲突 | 修复文件，`git add`，`git am --continue`。或 `git am --abort`。 |
| 樱桃选择冲突 | 修复文件，`git add`，`git cherry-pick --continue`。或 `--abort`。 |
| 检查中的MISMATCH | 审查并排输出。如果更改在功能上等价但上下文不同，与发送者确认。 |
| MISSING文件 | 发送者的更改可能根本没有应用。检查 `git am` 日志，如需要手动重新应用。 |
| EXTRA文件 | 通常没问题 — 接收方适配了上下文行。验证没有意外更改。 |

## 文件布局

```
your-repo/
├── .patch-pipeline.toml       # 配置（可选）
├── .patch-staging/
│   └── 2026-03-26/
│       ├── 0001-fix-timing.patch
│       ├── review_data.json    # 来自步骤1
│       ├── apply_data.json     # 来自步骤2
│       ├── check_data.json     # 来自步骤3 ⭐
│       ├── test_data.json      # 来自步骤4
│       └── REVIEW_REPORT.md    # 来自步骤5
└── (你的源代码)
```

## 运行测试

```bash
python -m pytest tests/ -v
```
