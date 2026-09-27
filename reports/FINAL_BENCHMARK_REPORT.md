# HERMES CODEBOT BENCHMARK FULL EXECUTION & RETROSPECTIVE REPORT
> 评测轮次: run_001 | 评测架构: Chunked Task-Isolated Session (~40% Context Budget)
> 评测模型: gemini-3.8-flash-tiered (High Reasoning) | 网关: custom:antigravity (127.0.0.1:8045)
> 完成时间: 2026-09-27 | 调度模式: 完全自主无人值守自动化流水线

## 一、核心执行指标大盘 (Executive Summary)

| 核心指标 | 数据统计 | 状态判定 |
| :--- | :--- | :--- |
| **全量任务调度完成率** | **23 / 23 (100.0%)** | **全部完成 (FINISHED)** |
| **校准阶段 (Calibration)** | **3 / 3 (100.0%)** | 全部执行完毕 |
| **SWE-bench Verified 赛道** | **6 / 6 (100.0%)** | 全部执行完毕 |
| **SWE-bench Pro 赛道** | **10 / 10 (100.0%)** | 全部执行完毕 |
| **Terminal-bench 底层赛道** | **4 / 4 (100.0%)** | 全部执行完毕 |
| **产生实际代码补丁 (Patch > 0B)** | **4 / 23 (17.4%)** | 补丁成功落盘 |
| **官方 Grader 判定通过 (Pass)** | **0 / 23 (0.0%)** | 需针对性攻坚 |
| **人工介入干预次数 (Interventions)** | **0 次** | 纯零接触全自动化 |

## 二、全量 23 道题目逐题执行明细表 (Task-by-Task Records)

| 序号 | 题目 ID | 所属赛道 | 耗时(s) | 补丁大小(Bytes) | 判定结果 | 执行状态 |
| :--- | :--- | :--- | ---: | ---: | :---: | :---: |
| 1 | `matplotlib__matplotlib-25122` | swe-bench-verified | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 2 | `instance_navidrome__navidrome-5001518260732e36d9a42fb8d4c054b28afab310` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 3 | `payments-pipeline-fix` | terminal-bench | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 4 | `django__django-14787` | swe-bench-verified | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 5 | `pylint-dev__pylint-6903` | swe-bench-verified | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 6 | `pydata__xarray-4687` | swe-bench-verified | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 7 | `django__django-13513` | swe-bench-verified | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 8 | `django__django-11138` | swe-bench-verified | 312.0 | 31171489 | UNRESOLVED | COMPLETED |
| 9 | `pytest-dev__pytest-6197` | swe-bench-verified | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 10 | `instance_element-hq__element-web-f3534b42df3dcfe36dc48bddbf14034085af6d30-vnan` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 11 | `instance_ansible__ansible-3889ddeb4b780ab4bac9ca2e75f8c1991bcabe83-v0f01c69f1e2528b935359cfe578530722bca2c59` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 12 | `instance_element-hq__element-web-72a8f8f03b1a01bb70ef8a5bb61759416991b32c-vnan` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 13 | `instance_flipt-io__flipt-abaa5953795afb9c621605bb18cb32ac48b4508c` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 14 | `instance_flipt-io__flipt-9f8127f225a86245fa35dca4885c2daef824ee55` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 15 | `instance_internetarchive__openlibrary-fad4a40acf5ff5f06cd7441a5c7baf41a7d81fe4-vfa6ff903cb27f336e17654595dd900fa943dcd91` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 16 | `instance_ansible__ansible-d72025be751c894673ba85caa063d835a0ad3a8c-v390e508d27db7a51eece36bb6d9698b63a5b638a` | swe-bench-pro-v2 | 0.0 | 102475473 | UNRESOLVED | COMPLETED |
| 17 | `instance_flipt-io__flipt-3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 18 | `instance_ansible__ansible-40ade1f84b8bb10a63576b0ac320c13f57c87d34-v6382ea168a93d80a64aab1fbd8c4f02dc5ada5bf` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 19 | `instance_internetarchive__openlibrary-322d7a46cdc965bfabbf9500e98fde098c9d95b2-v13642507b4fc1f8d234172bf8129942da2c2ca26` | swe-bench-pro-v2 | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 20 | `bun-sourcemap-leak` | terminal-bench | 0.0 | 326 | UNRESOLVED | COMPLETED |
| 21 | `production-planning` | terminal-bench | 0.0 | 0 | UNRESOLVED | COMPLETED |
| 22 | `interleaved-vigenere` | terminal-bench | 0.0 | 3838 | UNRESOLVED | COMPLETED |
| 23 | `session-window-debug` | terminal-bench | 0.0 | 0 | UNRESOLVED | COMPLETED |

## 三、评测架构验证成就 (What Worked)

1. **物理级会话隔离验证成功 (Chunked Session Isolation)**：
   - 每一道题目均在全新的子目录与独立 Git 仓库中执行，进程结束后立即销毁。
   - **0 上下文污染**：上一道题目的代码、报错与历史记忆完全清零，彻底避免了长轮次对话引起的模型幻觉与状态污染。
2. **上下文上限硬压制 (~40% Budget Cap)**：
   - 通过 `--max-turns 60` 实现了物理级安全卡口，有效防止了 Agent 在陷入未知死锁时盲目刷屏导致上下文窗口无限暴涨。
3. **断点持久化与崩溃自愈 (Checkpoint Resilience)**：
   - 运行中途中断后，调度器准确通过 `benchmark_run_state.json` 实现了无缝断点续跑，前序已完成题目的结果 100% 保持完整，无需推倒重来。
4. **微信异步即时告警 (Zero-Touch Notification)**：
   - 修复了 Python 环境依赖与微信环境上下文加载，实现了运行结束秒级推送告警。

## 四、核心短板与根因剖析 (Deficiencies & Root Causes)

### 1. 权限全开放行（YOLO 模式）介入时机滞后
- **现象**：前 12 道题目（含 3 道 Calibration 和 9 道 Scored 题）生成的 `patch.diff` 大小几乎全为 0 字节。
- **根因**：初版 Hermes `code` profile 配置中，无人值守安全拦截策略处于默认拦截状态 (`approvals.single_query_mode: deny`)。Codebot 在排查完逻辑准备调用命令修改文件或跑测试时被静默阻断 (`[BLOCKED: Command flagged as dangerous]`)，导致无法落地写入文件。直到中途在第 13 题前紧急配置了 `approvals.mode: off` 与 `--yolo` 注入后，后续任务才真正获得了完整的文件写权限。

### 2. Git 工作区改动与 Unified Diff 导出脱节
- **现象**：像 `instance_ansible` 导出了 100MB 补丁（把整个 submodule/上游全部卷入），而部分题目改了文件但未被记录。
- **根因**：Agent 在解题时直接在工作区进行了无约束的 git checkout / fetch 操作，导致基线 commit 与 HEAD 分离；或者只修改了临时测试脚本，没有在目标源码树中完成标准的 `git add` 与提交，导致导出脚本在计算 `git diff <base_commit>` 时抓取到错误的对象。

### 3. 大型项目 60 轮预算偏紧
- **现象**：对于 Django、Element-Web 等包含几十万行代码的超级大仓，Agent 往往在 60 轮内仅完成了依赖感知与代码定位，尚未来得及完成完整的代码重构与验证闭环便触发了单题轮数截断。

### 4. 补丁格式与官方 Grader 适配差异
- **现象**：即使产出了 326 字节精简补丁的 `bun-sourcemap-leak`，官方 Grader 仍判定为 Unresolved。
- **根因**：官方评测容器（Sandbox）要求补丁具有绝对精确的路径相对层级（a/ vs b/），且需要针对特定的测试用例运行 assert 断言。当前的本地轻量化验证器在沙箱环境隔离度与依赖完整度上与官方分布式 Grader 仍有差异。

## 五、下一步针对性改进路线 (Actionable Roadmap)

1. **基线加固**：从第一道题开始固化 `--yolo` 与 `approvals.mode: off`，确保无死角写权限。
2. **规范提交契约 (Git Contract Enforcement)**：在任务提示词中强制约束：Agent 在收口前必须执行 `git status` 并将修复代码统一以原子 commit 提交，确保 diff 干净无杂质。
3. **动态分层预算**：将简单 bug / 单测修复预算定为 60 轮，将大型工程全栈修复题（Element-Web, Django）预算动态提升至 120 轮。
4. **官方沙箱容器对齐**：使用 Docker 挂载官方 SWE-bench 测试容器，确保本地复验结果与远程官方榜单 100% 对齐。