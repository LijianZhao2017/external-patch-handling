# Bash脚本 — 快速开始

使用这些轻量级bash版本而不是Python以获得更快的启动和零依赖。

## 安装

无需安装！脚本是可执行的：

```bash
ls -la patch_*.sh
chmod +x patch_*.sh  # 如果需要
```

## 配置

与Python版本相同。创建 `.patch-pipeline.toml`：

```toml
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
```

或使用环境变量：

```bash
export PATCH_PIPELINE_WORKING_BRANCH="develop"
export PATCH_PIPELINE_BUILD_COMMAND="cargo build"
```

## 5步管道

### 步骤1：接收补丁
```bash
./patch_receive.sh /path/to/patches/
# 或
./patch_receive.sh ./patches/ --date 2026-03-25 --force
```

### 步骤2：应用到评审分支
```bash
./patch_apply.sh
# 或
./patch_apply.sh --date 2026-03-25
```

### 步骤3：检查等价性 ⭐
```bash
./patch_check.sh
# 显示：MATCH | PARTIAL | MISMATCH | MISSING | EXTRA
```

### 步骤4：运行测试
```bash
./patch_test.sh
# 运行：构建+单元测试+提示硅结果
```

### 步骤5：在批准后集成
```bash
./patch_integrate.sh
# 樱桃选择到工作分支
```

## 常见选项

所有脚本支持：

```bash
--date YYYY-MM-DD     # 指定暂存日期
--repo /path/to/repo  # 指定仓库路径
--help                # 显示用法
```

## 混合Python & Bash

根据你的偏好每步使用：

```bash
# Bash用于轻量级接收
./patch_receive.sh ./patches/

# Python用于详细检查
python patch_apply.py
python patch_check.py

# Bash用于速度
./patch_test.sh
./patch_integrate.sh
```

两者生成兼容的JSON，所以它们无缝协作。

## 与Python的主要差异

| 方面 | Bash | Python |
|------|------|--------|
| 启动 | 快速（~50ms） | 较慢（~500ms） |
| 依赖 | 零 | Python 3.11+ |
| 验证 | 基础 | 综合 |
| 路径过滤 | 未实现 | ✅ |
| 交互式备注 | 未实现 | ✅ |
| 相似度评分 | 简化 | 高级 |

对于大多数工作流，bash和Python产生等价结果。详见**BASH_IMPLEMENTATION.md**获取详细功能对比。

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| `patch_apply.sh not found` | 运行 `chmod +x patch_*.sh` |
| `git am --3way` 冲突 | 修复文件，运行 `git add`，然后 `git am --continue` |
| `未找到 .patch 文件` | 检查路径：`ls -la /path/to/patches/` |
| `工作树不清洁` | 暂存更改：`git stash` |

每个脚本的详细帮助，见**BASH_README_CN.md**。

## 性能

- **启动：** Bash快10倍（对于典型工作流可忽略）
- **Git操作：** 相同速度（git是瓶颈）
- **总体：** 对于实际使用没有显著差异

## 下一步

1. **尝试：** 运行 `./patch_apply.sh --help` 查看选项
2. **混合使用：** 在你偏好的地方使用bash，其他地方使用Python
3. **报告问题：** 用脚本输出和git日志提交bug报告
4. **贡献：** 通过拉取请求改进bash脚本

---

**开始：** `./patch_receive.sh ./your-patches/`
