# Bash 补丁管道脚本替代方案

这个目录现在包括所有Python补丁管道脚本的**bash版本**，当Python不可用或不首选时提供轻量级替代方案。

## 概述

| 步骤 | Python脚本 | Bash脚本 | 目的 |
|------|---|---|---|
| 1 | `patch_receive.py` | `patch_receive.sh` | 接收、验证和评审补丁 |
| 2 | `patch_apply.py` | `patch_apply.sh` | 将补丁应用到专用评审分支 |
| 3 | `patch_check.py` | `patch_check.sh` | 函数式等价性检查（发送者意图vs实际） |
| 4 | `patch_test.py` | `patch_test.sh` | 运行构建+单元测试+硅测试结果 |
| 5 | `patch_integrate.py` | `patch_integrate.sh` | 樱桃选择已评审补丁到工作分支 |

## 快速开始（Bash）

```bash
# 配置仓库（与Python版本相同）
cat > .patch-pipeline.toml << 'EOF'
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
EOF

# 步骤1：接收补丁
./patch_receive.sh /mnt/sharepoint/BHS-B0/2026-03-26/

# 步骤2：应用到评审分支
./patch_apply.sh

# 步骤3：检查等价性
./patch_check.sh

# 步骤4：运行测试
./patch_test.sh

# 步骤5：在批准后集成
./patch_integrate.sh
```

## 为什么使用Bash版本？

**优势：**
- ✅ **零依赖** — 仅需要 `bash`、`git`、标准Unix工具
- ✅ **轻量级** — 每个脚本~6–9 KB vs 多文件Python模块
- ✅ **直接shell集成** — 更容易与其他bash命令链接
- ✅ **POSIX友好** — 在macOS、Linux、BSD上运行无需修改
- ✅ **与Python共存** — 每次调用时选择使用哪个

**与Python版本的权衡：**
- 功能范围缩小：专注于核心操作（git、文件I/O、表格）
- 无静态代码检查或警告（如需可通过shell函数添加）
- JSON输出最少但与Python报告兼容
- 手动错误处理（类型安全性更低）

## 详细用法

### 步骤1：`patch_receive.sh`

```bash
# 从目录验证补丁
./patch_receive.sh /path/to/patches/

# 在特定日期下暂存
./patch_receive.sh /path/to/patches/ --date 2026-03-25

# 强制覆盖现有会话
./patch_receive.sh /path/to/patches/ --force
```

**输出：**
- 列出每个补丁的主题、作者、文件数、+/- 统计
- 标记二进制文件和缺失内容
- 将补丁复制到 `.patch-staging/<date>/`
- 为下游步骤创建 `review_data.json`

### 步骤2：`patch_apply.sh`

```bash
# 应用今天的暂存补丁
./patch_apply.sh

# 应用特定日期
./patch_apply.sh --date 2026-03-25

# 使用自定义仓库路径
./patch_apply.sh --repo /path/to/repo
```

**输出：**
- 创建评审分支：`review/<date>/<slug>`
- 用 `git am --3way` 应用所有补丁
- 冲突时暂停；用户可修复并继续
- 保存 `apply_data.json` 包含分支名称和提交哈希

**冲突时：**
```bash
# 修复冲突，然后继续
git add <resolved-files>
git am --continue

# 或中止
git am --abort && git checkout main && git branch -D review/...
```

### 步骤3：`patch_check.sh` ⭐ **关键步骤**

比较**发送者意图**（他们的补丁）vs **实际到达**（git diff）。

```bash
./patch_check.sh
./patch_check.sh --date 2026-03-25
./patch_check.sh --verbose   # 显示详细diffs
```

**输出表格：**

| 状态 | 文件 | 发送+/- | 接收+/- | 匹配% |
|------|------|----------|----------|---------|
| MATCH | src/fix.c | +10/-2 | +10/-2 | 100% |
| PARTIAL | src/config.h | +5/-1 | +4/-1 | 80% |
| MISMATCH | src/old.c | +20/-5 | +2/-10 | 20% |
| MISSING | src/test.c | +3/-0 | +0/-0 | 0% |
| EXTRA | src/new.c | +0/-0 | +15/-0 | N/A |

**解释：**
- **MATCH**（≥75%） — 相同逻辑更改正确到达
- **PARTIAL**（40–75%） — 更改部分存在；与发送者审查
- **MISMATCH**（<40%） — 显著分散；确认意图
- **MISSING** — 发送者触及但没有到达
- **EXTRA** — 接收者更改了发送者没有触及的文件（适配OK）

**输出：** 包含结果的 `check_data.json` 用于报告

### 步骤4：`patch_test.sh`

```bash
./patch_test.sh
./patch_test.sh --date 2026-03-25
./patch_test.sh --build-cmd "scons -j4"     # 自定义构建
./patch_test.sh --test-cmd "cargo test"     # 自定义测试
```

**做什么：**
1. 运行构建命令（默认：`make -j$(nproc)`）
2. 运行单元测试（默认：`pytest tests/`）
3. 提示输入硅/硬件测试结果（PASS/FAIL/PENDING）
4. 保存结果到 `test_data.json`

**输出：** 简单的PASS/FAIL摘要+日志

### 步骤5：`patch_integrate.sh`

```bash
./patch_integrate.sh
./patch_integrate.sh --date 2026-03-25
```

**做什么：**
1. 验证评审报告存在（可选LGTM检查）
2. 确认集成批准（交互式）
3. 签出工作分支
4. 樱桃选择所有评审提交到工作分支
5. 处理冲突同 `git am`

**成功时：**
```
✅ 所有提交已集成到main
后续步骤：
  1. 通过验证：git log --oneline -n 10
  2. 运行最终验证
  3. 推送到远程：git push origin main
```

## 配置

### 通过 `.patch-pipeline.toml`
所有脚本读取与Python版本相同的配置文件：

```toml
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
allowed_path_prefixes = ["src/", "include/"]
max_patch_size_kb = 5000
```

### 通过环境变量
覆盖任何配置设置：

```bash
export PATCH_PIPELINE_WORKING_BRANCH="develop"
export PATCH_PIPELINE_RELEASE="BHS-B1"
export PATCH_PIPELINE_BUILD_COMMAND="cargo build"
export PATCH_PIPELINE_UNIT_TEST_COMMAND="cargo test"

./patch_apply.sh
./patch_test.sh
```

## 混合Python和Bash

脚本**兼容** — 你可以自由混合使用：

```bash
# 使用Python进行接收（更彻底的验证）
python patch_receive.py ./patches/

# 用bash应用（轻量级）
./patch_apply.sh

# 用Python检查等价性（详细分析）
python patch_check.py

# 用bash测试
./patch_test.sh

# 用Python集成
python patch_integrate.py
```

两者都生成相同的JSON输出文件（`.patch-staging/<date>/*.json`），所以无论每个步骤使用哪种语言，管道都有效。

## 错误处理

### 常见问题

**`未找到 .patch 文件`**
```bash
# 验证补丁目录有 .patch 文件
ls -la /path/to/patches/
```

**`工作树不清洁`**
```bash
# 先暂存或提交更改
git stash
./patch_apply.sh
```

**`分支已存在`**
```bash
# 删除旧评审分支
git branch -D review/2026-03-26/fix-timing
./patch_apply.sh
```

**`git am --3way` 冲突**
```bash
# 手动解决
git add <fixed-files>
git am --continue
# 脚本将继续
```

**`测试失败`**
- 检查 `/tmp/build.log` 获取构建错误
- 检查 `/tmp/test.log` 获取测试失败
- 修复评审分支上的问题，再次测试

## 脚本内部

每个脚本：
1. **源配置** 来自 `.patch-pipeline.toml` 或环境变量（bash不原生解析TOML；脚本用grep提取关键值）
2. **验证前提条件** （干净的工作树、补丁文件、暂存目录）
3. **执行核心git命令** （`git am`、`git cherry-pick`、`git diff`）
4. **生成JSON输出** 用于下游工具
5. **优雅地处理错误** 提供清晰可操作的消息

### 代码组织

```bash
# 每个脚本的标准结构：
set -euo pipefail          # 错误时失败、未定义变量、管道错误

# 配置部分
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
# ... 解析 --args

# 辅助函数
die() { echo "❌ $*" >&2; exit 1; }
log_success() { echo "✅ $*"; }
git_run() { git --no-pager -C "$REPO_PATH" "$@"; }
# ... 其他辅助函数

# 验证部分
[[ -d "$REPO_PATH" ]] || die "..."

# 核心逻辑
# ... 做工作

# 输出部分
echo "$JSON_DATA" | tee "$OUTPUT_FILE"
```

## 测试Bash脚本

验证bash脚本与你的仓库一起工作：

```bash
# 创建测试补丁
git format-patch -1 -o ./test-patches/ HEAD

# 测试管道
mkdir -p .patch-staging/$(date +%Y-%m-%d)
./patch_receive.sh ./test-patches/

./patch_apply.sh

./patch_check.sh

# 清理测试
git branch -D review/*/test-* || true
```

## Bash vs Python的限制

| 功能 | Python | Bash |
|------|--------|------|
| 丰富验证 | ✅ | ⚠️ 基础 |
| 静态代码检查 | ✅ | ❌ |
| JSON生成 | ✅ 完整 | ✅ 最小 |
| 路径过滤 | ✅ | ⚠️ 简单正则 |
| 错误消息 | ✅ 详细 | ✅ 清晰 |
| 依赖检查 | ✅ | ❌ |
| 性能 | ⚠️ 启动慢 | ✅ 快速 |

## 贡献

改进bash脚本：
1. 用 `set -euo pipefail` 规范修复bug
2. 添加新验证检查作为辅助函数
3. 保持JSON输出与Python版本兼容
4. 在macOS和Linux上测试
5. 记录与Python行为的偏差

---

**总结：** 当你想要轻量级、零依赖的补丁管理时使用bash脚本。当你需要高级验证和分析时使用Python版本。两者在同一管道中和平共存。
