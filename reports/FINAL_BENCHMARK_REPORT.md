# run_001 历史基础设施试运行记录（非性能报告）
> 评测轮次: run_001 | 评测架构: Chunked Task-Isolated Session (~40% Context Budget)
> 评测模型: gemini-3.8-flash-tiered (High Reasoning) | 网关: custom:antigravity (127.0.0.1:8045)
> 完成时间: 2026-09-27 | 调度模式: 历史运行记录；中途发生配置介入

> **历史有效性：** `run_001` 已归类为 `INFRASTRUCTURE_SHAKEDOWN` / `PROTOCOL_INVALIDATED_FOR_PERFORMANCE`。`RECORDED_LEGACY_RESULT = 0/23` 仅是旧产物的记录值，**NOT VALID FOR PERFORMANCE INTERPRETATION**；旧 grader、fresh regrade 和 telemetry 文件不能证明一次有效的正式性能测量。见 `runs/run_001/RUN_VALIDITY.json`。

## 一、核心执行指标大盘 (Executive Summary)

| 核心指标 | 数据统计 | 状态判定 |
| :--- | :--- | :--- |
| **旧调度记录数** | **23 / 23** | 仅表示旧产物覆盖 23 题，不证明任务有效完成 |
| **旧校准记录数** | **3 / 3** | 非有效校准 |
| **SWE-bench Verified 旧记录** | **6 / 6** | 非有效赛道结果 |
| **SWE-bench Pro 旧记录** | **10 / 10** | 非有效赛道结果 |
| **Terminal-bench 旧记录** | **4 / 4** | 非有效赛道结果 |
| **旧产物非空补丁 (Patch > 0B)** | **4 / 23 (17.4%)** | 未证明补丁基线正确 |
| **历史 Grader 文件记录通过** | **0 / 23** | 旧记录，非正式性能分数 |
| **人工介入干预次数 (Interventions)** | **精确次数未知** | 已记录 run 级配置与基础设施介入 |

## 二、全量 23 道题目逐题执行明细表 (Task-by-Task Records)

| 序号 | 题目 ID | 所属赛道 | 耗时(s) | 补丁大小(Bytes) | 判定结果 | 执行状态 |
| :--- | :--- | :--- | ---: | ---: | :---: | :---: |
| 1 | `matplotlib__matplotlib-25122` | swe-bench-verified | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 2 | `instance_navidrome__navidrome-5001518260732e36d9a42fb8d4c054b28afab310` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 3 | `payments-pipeline-fix` | terminal-bench | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 4 | `django__django-14787` | swe-bench-verified | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 5 | `pylint-dev__pylint-6903` | swe-bench-verified | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 6 | `pydata__xarray-4687` | swe-bench-verified | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 7 | `django__django-13513` | swe-bench-verified | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 8 | `django__django-11138` | swe-bench-verified | 312.0 | 31171489 | LEGACY_UNVERIFIED | RECORDED |
| 9 | `pytest-dev__pytest-6197` | swe-bench-verified | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 10 | `instance_element-hq__element-web-f3534b42df3dcfe36dc48bddbf14034085af6d30-vnan` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 11 | `instance_ansible__ansible-3889ddeb4b780ab4bac9ca2e75f8c1991bcabe83-v0f01c69f1e2528b935359cfe578530722bca2c59` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 12 | `instance_element-hq__element-web-72a8f8f03b1a01bb70ef8a5bb61759416991b32c-vnan` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 13 | `instance_flipt-io__flipt-abaa5953795afb9c621605bb18cb32ac48b4508c` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 14 | `instance_flipt-io__flipt-9f8127f225a86245fa35dca4885c2daef824ee55` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 15 | `instance_internetarchive__openlibrary-fad4a40acf5ff5f06cd7441a5c7baf41a7d81fe4-vfa6ff903cb27f336e17654595dd900fa943dcd91` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 16 | `instance_ansible__ansible-d72025be751c894673ba85caa063d835a0ad3a8c-v390e508d27db7a51eece36bb6d9698b63a5b638a` | swe-bench-pro-v2 | 0.0 | 102475473 | LEGACY_UNVERIFIED | RECORDED |
| 17 | `instance_flipt-io__flipt-3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 18 | `instance_ansible__ansible-40ade1f84b8bb10a63576b0ac320c13f57c87d34-v6382ea168a93d80a64aab1fbd8c4f02dc5ada5bf` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 19 | `instance_internetarchive__openlibrary-322d7a46cdc965bfabbf9500e98fde098c9d95b2-v13642507b4fc1f8d234172bf8129942da2c2ca26` | swe-bench-pro-v2 | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 20 | `bun-sourcemap-leak` | terminal-bench | 0.0 | 326 | LEGACY_UNVERIFIED | RECORDED |
| 21 | `production-planning` | terminal-bench | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |
| 22 | `interleaved-vigenere` | terminal-bench | 0.0 | 3838 | LEGACY_UNVERIFIED | RECORDED |
| 23 | `session-window-debug` | terminal-bench | 0.0 | 0 | LEGACY_UNVERIFIED | RECORDED |

## 三、历史运行可确认范围

历史脚本尝试按题目启动独立 Hermes 进程，且设置了 `--max-turns 60`。但 workspace 未恢复真实题目基线，过程 telemetry 不完整，不能由这些记录证明上下文无污染、解题流程完整、断点自愈或有效评分。表中的 0.0 秒和判定值只是旧产物字段，不是有效测量。

## 四、核心短板与根因剖析 (Deficiencies & Root Causes)

### 1. 权限全开放行（YOLO 模式）介入时机滞后
- **现象**：前 12 道题目（含 3 道 Calibration 和 9 道 Scored 题）生成的 `patch.diff` 大小几乎全为 0 字节。
- **根因**：初版 Hermes `code` profile 配置中，无人值守安全拦截策略处于默认拦截状态 (`approvals.single_query_mode: deny`)。Codebot 在排查完逻辑准备调用命令修改文件或跑测试时被静默阻断 (`[BLOCKED: Command flagged as dangerous]`)，导致无法落地写入文件。直到中途在第 13 题前紧急配置了 `approvals.mode: off` 与 `--yolo` 注入后，后续任务才真正获得了完整的文件写权限。

### 2. Git 工作区改动与 Unified Diff 导出脱节
- **现象**：像 `instance_ansible` 导出了 100MB 补丁（把整个 submodule/上游全部卷入），而部分题目改了文件但未被记录。
- **根因**：Agent 在解题时直接在工作区进行了无约束的 git checkout / fetch 操作，导致基线 commit 与 HEAD 分离；或者只修改了临时测试脚本，没有在目标源码树中完成标准的 `git add` 与提交，导致导出脚本在计算 `git diff <base_commit>` 时抓取到错误的对象。

### 3. 轮数瓶颈未证实
- 当前 duration、model usage 和事件记录无效，无法判断 60 轮是否为失败原因。新协议保持 60 轮。

### 4. 补丁格式与官方 Grader 适配差异
- **现象**：`bun-sourcemap-leak` 产出了 326 字节补丁，旧 `grader-result.json` 记录为 Unresolved。
- **证据边界**：历史脚本未实际调用官方 Grader，因此不能从该记录判断补丁是否通过官方测试，也不能确认路径格式是失败根因。

## 五、下一步针对性改进路线 (Actionable Roadmap)

1. **配置冻结**：新 run 启动前记录并冻结 SUT 审批配置；运行中改变配置则标记性能结果失效。
2. **机械补丁导出**：由 runner 记录基线与工作区状态，机械生成并校验补丁，不依赖 Agent 自行提交。
3. **真实官方验证**：调用固定版本的官方 verifier，并保存命令、退出码及原始输出后再解析结果。
