# jev 模型工具调用审核能力评测报告

> 评测数据：40 个现网 badcase × 2 种源输出 × 判断标准中英两语言，共 160 条/方案

---

## 一、背景与目标

我们的工具调用中控系统采用"快慢模型"架构：快模型（qwq32b）从候选工具中规划并输出工具调用，慢模型负责全量审核。当前的主要瓶颈是：

1. **快模型输出质量不足**，错误输出必须依赖慢模型全量审核才能拦下，慢模型成本高、延迟大；
2. **缺少一个轻量的中间审核层**，在慢模型之前先做一道判别，把明显正确的输出直接放行、把可疑输出拦下转慢模型。

**jev（System One）是一个判别式模型**：输入 state（结构化上下文）+ 若干 typed questions（类型化问题），输出结构化答案——是非题（noul）给出 0~1 概率，选择题（choice）给出选中项、全选项概率分布和置信度。它不做生成、只做判别，天然适合做"快模型输出审核器"。

**本次评测目标**：验证 jev 能否准确判断"快模型的工具调用输出是否正确"，从而替代慢模型的大部分全量审核工作量。我们设计了三种输入组织方案，各在中英两语言上完成了 160 条批跑评测。

### 评测设置

- **样本**：40 个真实 badcase（快模型实际出错的场景）。每个 case 取两种源输出：
  - `answer`：快模型的**真实错误输出**（负样本，期望 jev 判"错误"并拦下）；
  - `gold`：人工标注的**标准正确输出**（正样本，期望 jev 判"正确"并放行）。
- 每语言 40×2=80 条，中英共 160 条/方案；三个方案使用完全相同的样本，结果可直接对比。
- **指标口径**（tp=正向判正向、fn=正向判负向、fp=负向判正向、tn=负向判负向）：

| 指标 | 定义 | 含义 |
|---|---|---|
| acc | (tp+tn)/总数 | 整体准确率 |
| catch_rate | tn/(tn+fp) | **负样本检出率**：错误输出被拦下的比例（业务最关心） |
| false_alarm | fn/(tp+fn) | **正样本误报率**：正确输出被误拦的比例（误拦越多，慢模型越省不下来） |

理想目标是 catch_rate 尽量高（错误都拦下）、false_alarm 尽量低（正确的直接放行，不用过慢模型）。

---

## 二、方案一：全量 prompt 直判

### 思路

最直接的用法：把快模型收到的**完整原始 prompt**（system 规则 + 候选工具定义 + 参考信息 + 多轮对话历史，单条约 1.2 万字）原样作为 state 交给 jev，只问一个是非题（noul）："`model_output` 是否是针对 `last_query` 的正确工具调用？"。jev 需要自己从大段自由文本中理解工具规则并做出综合判断。

### 示例（case01，中文）

**state**（3 个字段）：

```json
{
  "prompt": "<|im_start|>system\n你是一个AI助手系统中的工具调用助手……# 术语说明 1. 单任务vs多任务……# 工具调用原则 1. 如果工具参数描述中没有特殊说明，则该参数为非必选参数……[完整 system 提示词 + 全部候选工具定义 + 参考信息 + 对话历史，共约 11885 字]",
  "last_query": "Hello",
  "model_output": "turn2.task1:Confirm()"
}
```

**question**（1 个 noul）：

```json
{
  "type": "noul",
  "instructions": "`prompt` 字段包含工具调用的指令说明、候选工具、参考信息和对话历史，`last_query` 是用户的最新请求。请基于以上全部信息判断：`model_output` 是否是针对 `last_query` 的正确工具调用？判断所选工具和每个参数值是否正确，turn 编号不影响判断。",
  "criteria": {
    "true":  "该工具调用正确满足了用户的最新请求：从候选工具中选出了正确的工具，且每个参数值都能在对话或参考信息中找到正确依据……",
    "false": "该工具调用存在任何错误：应该调用另一个工具（包括当没有任何候选工具能满足请求时应调用 SubmitSlowAgent，或在错误对话状态下使用了 Confirm/Deny/Select 决策工具）；参数缺失、错误或属于凭空猜测……"
  }
}
```

jev 返回 `noul` 概率，≥ 阈值判"正确输出"（放行），否则判"错误输出"（拦下转慢模型）。

### 指标
> 注：tp=拦住answer(好)、 fn=漏放answer(漏放行)、 fp=拦住gold(误拦) 、tn=放行gold(好)

| 语言 | acc@0.5 | tp / fn / fp / tn @0.5 | catch_rate@0.5 | false_alarm@0.5 | best阈值 | acc@best | tp / fn / fp / tn @best | catch@best | FA@best | 单条请求平均耗时 | 服务端平均输入 token |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EN | 76.25% | 29 / 11 / 8 / 32 | 80.0% | 27.5% | 0.1 | 77.5% | 35 / 5 / 13 / 27 | 67.5% | 12.5% | 5734 ms | 7807 |
| CN | 78.75% | 29 / 11 / 6 / 34 | 85.0% | 27.5% | 0.4 | 80.0% | 30 / 10 / 6 / 34 | 85.0% | 25.0% | 5781 ms | 7778 |

### 补充示例：正负样本对照（case26，中文，"1:50帮我关闭番茄畅听"）

| 源输出 | model_output | jev noul | 判定 | 结果 |
|---|---|---|---|---|
| answer（错误输出） | `turn6.task1:CreateAlarm(time=1:50,event=关闭番茄畅听)` ——把"定时关应用"误解为"建闹钟" | **0.001** | <0.5 判错误 → 拦下 | ✓ 正确拦截 |
| gold（正确输出） | `turn1.task1@TimeEvent(time=1:50)#关闭番茄畅听:CloseApp(appName=番茄畅听)` ——时间条件挂 TimeEvent，动作是关应用 | **0.953** | ≥0.5 判正确 → 放行 | ✓ 正确放行 |

此例可见方案一的分数区分度：jev 自己从 1.2 万字 prompt 中理解了"定时任务用条件工具挂载、而非建闹钟"的规则，对错误输出给出 0.001 的极低分。但这类高分/低分两极分明的 case 并非全部——约三成正确输出的分数落在 0.5 附近，是误报的主要来源。

### 小结

- 优点：零改造，直接可用；中文在 0.5 阈值下 catch 85% 已可用。
- 缺点：**误报普遍偏高（FA 27.5%）**——约四分之一的正确输出会被误拦，省不掉这部分慢模型审核；且 jev 需要自己消化 1.2 万字自由文本 prompt，输入 token 开销最大。

---

## 三、方案二：结构化 state + 单个综合是非题

### 思路

把原始 prompt **解析重组为结构化 state**：system 规则提炼为 `system_rules`、候选工具按用途分类为 `candidate_tools`（condition_tools / normal_tools / decision_tools / special_tools）、参考信息归类为 `reference_info`、对话历史规范化为 `messages`。question 仍是一个综合 noul，但 instructions 中逐字段说明含义，让 jev 在清晰的结构上做同一个综合判断。

### 示例（case01，中文）

**state**（6 个字段，prompt 长度压缩约 60%）：

```json
{
  "system_rules": "# 术语说明 1. 单任务vs多任务…… # 工具调用原则 1. 非必选参数处理……[提炼后的关键规则]",
  "candidate_tools": {
    "condition_tools": "[时间/地点/事件前置条件工具]",
    "normal_tools":    [{"name": "ExtractInformation", "description": "提取图片中的内容", "input_schema": {...}}, ...],
    "decision_tools":  "[Confirm/Deny/Select：用于回应对话中处于确认/选择状态的决策]",
    "special_tools":   "[SubmitSlowAgent：全局兜底]"
  },
  "reference_info": {"当前屏幕信息": {"object": "图片", "id": "1788…", "information": {...}}, ...},
  "messages": [
    {"role": "tool", "content": "[{\"toolName\":\"ScanPerformance\",\"status\":\"confirm\",\"responseText\":\"即将帮你清理共计3.22GB应用缓存，是否确认清理？\"}]"},
    {"role": "user", "content": "Hello"}
  ],
  "last_query": "Hello",
  "model_output": "turn2.task1:Confirm()"
}
```

**question**（1 个 noul，instructions 说明各字段含义后综合判断）：

> 请基于以上信息判断：`model_output` 是否是针对 `last_query` 的正确工具调用？检查请求的每个子任务是否都被覆盖、所选工具是否是 `candidate_tools` 中的正确工具、每个参数值是否在 `last_query`、`messages` 或 `reference_info` 中有依据、输出是否符合 `system_rules`。

### 指标

| 语言 | acc@0.5 | tp / fn / fp / tn @0.5 | catch_rate@0.5 | false_alarm@0.5 | best阈值 | acc@best | tp / fn / fp / tn @best | catch@best | FA@best | 单条请求平均耗时 | 服务端平均输入 token |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EN | 71.25% | 27 / 13 / 10 / 30 | 75.0% | 32.5% | 0.1 | 81.25% | 37 / 3 / 12 / 28 | 70.0% | 7.5% | 4716 ms | 6266 |
| CN | 73.75% | 26 / 14 / 7 / 33 | 82.5% | 35.0% | 0.2 | 81.25% | 35 / 5 / 10 / 30 | 75.0% | 12.5% | 4772 ms | 6247 |

> 注：方案一/二 best 阈值下的 tp/fn/fp/tn 由阈值扫描表的 catch_rate/false_alarm 按每类 40 条推算。

### 补充示例：正负样本对照（case26，中文，"1:50帮我关闭番茄畅听"）

state 同为结构化 6 字段（`system_rules` / `candidate_tools` / `reference_info` / `messages` / `last_query: "1:50帮我关闭番茄畅听"` / `model_output`），question 为同一个综合 noul。jev 返回：

| 源输出 | model_output | jev noul | 判定 | 结果 |
|---|---|---|---|---|
| answer（错误输出） | `turn6.task1:CreateAlarm(time=1:50,event=关闭番茄畅听)` | **0.0004** | <0.5 判错误 → 拦下 | ✓ 正确拦截 |
| gold（正确输出） | `turn1.task1@TimeEvent(time=1:50)#关闭番茄畅听:CloseApp(appName=番茄畅听)` | **0.844** | ≥0.5 判正确 → 放行 | ✓ 正确放行 |

对比方案一同 case 的分数（0.001 / 0.953），结构化 state 下分数更保守（gold 从 0.953 降到 0.844，更靠近 0.5）——这正是方案二"分数整体偏低、best 阈值落到 0.1~0.2"现象的微观体现：结构化压缩了信息量，jev 的把握度下降，分数向中间收缩。

### 小结

- 优点：输入 token 较方案一降约 20%，延迟降约 18%；**best 阈值下误报显著改善**（EN FA 仅 7.5%）。
- 缺点：0.5 默认阈值下的 catch_rate 和误报均不如方案一；单题综合判断把"选错工具、参数幻觉、漏子任务、误用兜底"等不同维度的错误压成一个分数，边界模糊，阈值不稳定（best 阈值低到 0.1~0.2，说明分数整体分布偏低且分离度有限）。

---

## 四、方案三：原子问题拆解 + 多问题单请求 + 分层融合判定

### 思路

把"输出是否正确"这一个综合判断**拆解为 7 类原子问题**，利用 jev 官方的多问题单请求能力（一次请求并行评估全部问题，延迟只增加一次）。每类问题只问一个维度、答案语义单一，再由程序按分层规则融合为最终判定。

**决策工具处理**：仅当对话历史任意一轮工具结果中出现 `status=confirm`（加入 Confirm、Deny）或 `status=select`（加入 Select）时才加入，是否该选由 jev 判断。

### 7 类原子问题

| 问题 | 类型 | 问什么 | 何时问 / 裁剪规则                                                                  | 80 条中实际提问次数 |
|---|---|---|-----------------------------------------------------------------------------|---|
| **coverage** | noul | `model_output` 是否覆盖了 `last_query` 的每个功能性子任务 | 始终问                                                                         | 80 |
| **fallback** | noul | 不管实际输出，`last_query` 本身是否属于应使用 SubmitSlowAgent 的场景（无普通工具可满足 / 复杂多步 / 子任务有依赖 / 纯闲聊） | 始终问                                                                         | 80 |
| **tool_choice_N** | choice | 针对每个子任务：完成它最合适的是哪个工具？选项 = 全部普通工具 + SubmitSlowAgent + 符合历史状态的决策工具 | 非SubmitSlotAgnet时才问| 68 |
| **condition_needed** | noul | `last_query` 是否表达了需要挂载到任务上的前置条件（时间/地点/事件） | 输出含普通工具调用时问                                                                 | 61 |
| **condition_correct** | noul | 输出中使用的条件工具是否选对（条件类型对、参数值对） | 仅当输出带条件工具时问（本批仅 2 条）                                                        | 2 |
| **param_grounded** | noul | 输出的每个参数值是否都在对话/参考信息中有依据、无凭空猜测 | 被调工具中至少一个有参数时问                                                         | 54 |
| **slot_missing** | noul | 是否遗漏了本应输出的参数（用户明确提及的、或工具 schema 必选的） | 被调工具中至少一个有参数时问                                                                         | 54 |

每条请求实际问 2~7 题（中位数 6 题）。

**各原子问题判别力**（answer 与 gold 两个来源的分数均值差，差值越大表示这个问题区分能力越强）：

- **强**：coverage、param_grounded、slot_missing（均值差 0.4~0.55，两类样本分布分离明显，是融合判定的主力信号）；
- **中**：tool_choice（jev 针对每个子任务独立选出"最合适的工具"，选中项与快模型实际调用一致为"命中"＝放行信号，不一致为拦截信号。EN：错误输出 36 条中 13 条被 jev 选出不同工具＝识破选错工具；
正确输出 27 条中仅 4 条选偏＝误拦风险小）；
- **弱（单独看）**：fallback（两类样本均值几乎同分布）——但对"兜底输出"这一子集是唯一有效信号；condition_needed（几乎全判 0.008，本批基本无效）；condition_correct 样本太少无统计意义。

### 分层融合判定（选定配置，两语言共用统一阈值）

```
若快模型输出为SubmitSlowAgent:
    fallback 分数 < 0.2  → 拦下
否则（非SubmitSlowAgent）:
    coverage < 0.4  或  param_grounded < 0.3  或  slot_missing < 0.4  → 拦下
    否则放行
```

即：SubmitSlowAgent输出只看"这个 query 是不是真该兜底"（fallback 题）；非兜底输出看三个强信号题，任一低于阈值即拦。分层解决的问题是：coverage 题会把"该兜底而没兜底"误伤为"未覆盖"，兜底类正样本需要单独走 fallback 通道。

### 示例（case01，中文）

**state**：与方案二完全一致（结构化 6 字段）。该 case 对话历史中 ScanPerformance 工具结果处于 `status=confirm`，故 tool_choice_1 的选项中加入了 Confirm、Deny。**一次请求共 4 个问题**：

| 问题 | 类型 | 关键内容 | jev 返回 |
|---|---|---|---|
| coverage | noul | 是否覆盖每个功能性子任务并过滤闲聊（用户只说了"Hello"） | **0.107** |
| fallback | noul | "Hello"是否属于纯闲聊应兜底场景 | 0.547 |
| tool_choice_1 | choice | 选项=[ExtractInformation, ScanPerformance, CheckStorage, CloseApp, SetSetting, **Confirm, Deny**, SubmitSlowAgent] | Confirm（conf 0.758） |
| condition_needed | noul | 是否有前置条件 | 0.001 |

**融合判定**：输出非兜底 → coverage 0.107 < 0.4 → **拦下** ✓（该 answer 是错误输出——纯闲聊不应 Confirm，正确拦下）。

多工具案例（case08，`model_output: turn2.task1:StopRecordScreen()`，一次请求 6 个问题）：该条为 answer（错误输出），jev 返回 coverage=0.072、param_grounded=0.085、slot_missing=0.245、tool_choice_1=StopRecordScreen（conf 0.671）等，融合判定 coverage 0.072 < 0.4 → **拦下** ✓；同 case 的 gold 输出各题分数均在阈值之上，正确放行。

### 指标

方案三的"阈值"是分层融合的多个阈值组合。@0.5 指各题统一取 0.5；best 指上文选定配置（兜底 fallback<0.2；非兜底 coverage<0.4 OR param_grounded<0.3 OR slot_missing<0.4）。

| 语言 | acc@0.5 | tp / fn / fp / tn @0.5 | catch_rate@0.5 | false_alarm@0.5 | best配置 | acc@best | tp / fn / fp / tn @best | catch@best | FA@best | 单条请求平均耗时 | 服务端平均输入 token/题 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EN | 80.0% | 29 / 11 / 5 / 35 | 87.5% | 27.5% | 分层 fb0.2 / cov0.4-pg0.3-sm0.4 | 83.75% | 33 / 7 / 6 / 34 | 85.0% | 17.5% | 20076 ms | 36295 |
| CN | 76.25% | 26 / 14 / 5 / 35 | 87.5% | 35.0% | 分层 fb0.2 / cov0.4-pg0.3-sm0.4 | 81.25% | 32 / 8 / 7 / 33 | 82.5% | 20.0% | 20065 ms | 36286 |

> 延迟口径：一次请求并行评估全部问题（中位 6 题），约 20s 返回全部答案；输入 token 为服务端统计的每题平均。

### 补充示例：正负样本对照（case26，中文，"1:50帮我关闭番茄畅听"）

state 与方案二相同。两源的**一次请求各问题及融合判定**：

**answer（错误输出）`turn6.task1:CreateAlarm(time=1:50,event=关闭番茄畅听)`** ——问 6 题：

| 问题 | jev 返回 | 信号 |
|---|---|---|
| coverage | **0.001** | 闹钟不覆盖"关闭应用"子任务 |
| fallback | 0.022 | 该请求可由普通工具完成，不该兜底 |
| tool_choice_1 | **CloseApp**（conf 0.968） | jev 认为该用 CloseApp，而快模型用了 CreateAlarm → 不命中 |
| condition_needed | 0.173 | 时间条件应挂载（快模型把它当成了闹钟参数） |
| param_grounded | **0.002** | 参数值无依据 |
| slot_missing | **0.004** | 漏参数 |

融合判定：非兜底输出，coverage 0.001 < 0.4 → **拦下** ✓（param_grounded/slot_missing 双双跌破阈值，是比 coverage 更"实"的证据）

**gold（正确输出）`turn1.task1@TimeEvent(time=1:50)#关闭番茄畅听:CloseApp(appName=番茄畅听)`** ——输出带条件工具，问 4 题：

| 问题 | jev 返回 |
|---|---|
| coverage | 0.993 |
| fallback | 0.0001 |
| tool_choice_1 | CloseApp（conf 0.917，与快模型一致 → 命中） |
| condition_correct | 0.808（TimeEvent(time=1:50) 条件选对、参数对） |

融合判定：coverage 0.993 ≥ 0.4 → **放行** ✓

> 注：该 gold 行漏问了 param_grounded/slot_missing（条件参数值 "1:50" 中的冒号干扰了 model_output 的程序化解析，致被调工具未识别、两题被裁掉）。这是程序化裁剪的已知边界情况，全量 160 条中仅此 1 case（中英各 1 行）受影响，且未影响该条最终判定。

### 小结

- **best 配置下三个方案中最优**：EN 83.75% / CN 81.25%，且**漏放行（fn）从方案一/二的 10~14 条降到 7~8 条**——即真正流到线上的错误输出更少；
- 误报（FA）降到 17.5%~20%，比方案一/二 0.5 阈值下的 27.5%~35% 明显改善；
- catch_rate 与 false_alarm 可以通过各题阈值独立调节，业务上可按"宁可误拦"或"宁可放行"灵活取舍；
- 代价：延迟（~20s）和输入 token（~3.6 万/题）显著高于方案一/二，因为多问题请求中每题都携带完整 state；后续可通过缩短每题 instructions（共享字段说明）压缩。

---

## 五、四方案对比总览
通过jev
1、提升快系统的准确率，尤其是那些低级错误
2、解耦慢系统，所有的都不要审

对比开源jev和searchJev

快系统出SubmitSlowAgent不考虑
扩充badcase 100+
目标：轻量化、通用
catch@best：>80%
FA@best (EN/CN)：<2%——优先
时延：<100ms

1. 给模型jev输入是啥：最小（必要）集合上下文 + 经验（判断原则）
2. 分析每条case，是否有测试数据本身就有问题（比如工具描述不好）


| 方案 | 输入组织 | 问题形式 | acc@0.5 (EN/CN) | acc@best (EN/CN) | catch@best (EN/CN) | FA@best (EN/CN) | 延迟 | 输入 token |
|---|---|---|---|---|---|---|---|---|
| 一：全量 prompt | 原始 prompt 直传 | 1 个综合 noul | 76.25% / 78.75% | 77.5% / 80.0% | 67.5% / 85.0% | 12.5% / 25.0% | ~5.7s | ~7.8k |
| 二：结构化 state | 解析重组 6 字段 | 1 个综合 noul | 71.25% / 73.75% | 81.25% / 81.25% | 70.0% / 75.0% | 7.5% / 12.5% | ~4.7s | ~6.3k |
| 三：原子问题 | 同方案二 | 2~7 题/请求（noul+choice） | 80.0% / 76.25% | **83.75% / 81.25%** | **85.0% / 82.5%** | 17.5% / 20.0% | ~20s | ~3.6万 |
| 四：条件触发（规划） | 同方案二 | 命中易错模式才触发，1~2 题定向 | — | 待评测 | 预期 ≥ 方案三 | 预期仅触发路径 | 触发时 ~4.7s | 触发时 ~6.3k |

## 六、方案四（规划中）：动态条件触发 + 高频易错场景精准打击

### 动机：错误不是均匀分布的

前三个方案都是"每条输出都过一遍 jev"。但分析 40 个 badcase 的错误类型分布后发现，快模型的错误高度集中在两类场景：

| 错误类型 | case 数 | 占比 | 典型例子 |
|---|---|---|---|
| **工具选择错误**（含误用兜底/决策工具） | 29/40 | 72.5% | case10"打开华为分享"→OpenApp（应为 TurnOnHuaweiShare）；case34"拍照翻译"→LaunchTranslationTool（应为 OpenHivisionFunction） |
| **工具选对但参数/形态错误**（漏槽位、参数值错、缺条件挂载） | 11/40 | 27.5% | case20 SetVolume 漏 volumeType；case22 OpenApp 漏 type；case38 CheckAlarm 漏 rangeType=all |

而方案三的顽固漏放行（融合判定没拦住的 answer）恰好也落在这两类里：EN 6 条中 4 条是工具混淆（case10/22/34/38），CN 7 条中 5 条（case10/20/22/34/38）——**与其全量过 jev，不如针对特定"案发现场"精准打击**：只在快模型输出命中已知易错模式时才触发 jev，且只问与该场景直接相关的问题。

### 设计

**触发层（代码判定，零成本）**：对快模型输出做轻量解析，命中预设的易错模式才触发 jev 审核，否则直接放行。触发规则来自线上 badcase 的持续统计，如：

- **场景一：工具混淆型**——某工具历史上高频被错选（如 OpenApp 被用来打开实际有专用开关的功能）。当 `chosen_tool ∈ {高频易错工具名单}` 时触发。本批 40 case 中，answer 源被调工具的频次已呈现集中度：Confirm（6 次）、SubmitSlowAgent（4 次）、SetSmarthomeDeviceLuminance / TurnOffSmarthomeDevice / OpenApp / CreateAlarm / TurnOnSetting（各 3 次）——名单可以按线上统计动态维护。
- **场景二：关键槽位漏传型**——某工具选对但历史上高频漏传关键参数（如 book_flight 漏舱位、SetVolume 漏 volumeType）。当 `chosen_tool == "X"` 且输出缺少关键槽位时触发。

**审核层（jev，按场景定制问题）**：触发后不做全问题集，只问该场景的问题，state 沿用方案二/三的结构化形式：

- 场景一触发 → 问 1 个 **choice**："完成该子任务最合适的是哪个工具？"选项 = 候选工具 + 与被调工具易混的近义工具 + SubmitSlowAgent。jev 选中项 ≠ 快模型实际调用 → 拦下。这是方案三 tool_choice 题的定向化：本批中该题在错误输出上识破率 36%（13/36）、正确输出误拦仅 15%（4/27），聚焦到混淆高发工具后预期两项都会显著改善；
- 场景二触发 → 问 1~2 个 **noul**："该输出是否遗漏了本应输出的参数（用户提及的、或该工具在本场景的关键槽位）？"（即方案三 slot_missing 题的定向化，可针对具体工具在 criteria 里写明关键槽位清单）。低于阈值 → 拦下。

---

## 七、结论与建议

1. **jev 具备担任快模型输出审核器的能力**。最优配置下整体准确率 81~84%，负样本检出率 82.5~85%，即约六分之五的错误输出可在慢模型之前被拦下。
2. **方案三（原子问题 + 分层融合）是三个方案中效果最好的**：错误输出的漏放行最少（每语言仅 7~8 条/80），误报可控，且各维度阈值可独立调节，适合按业务风险偏好定制。顽固漏放行的 6~7 条 badcase 已在逐条明细中标注（筛选"融合hit=False"），多为近义工具混淆和多轮状态判断类，是下一步优化的靶点。
3. **方案二是成本敏感场景的可行备选**：延迟最低（~4.7s）、token 最省，best 阈值下 EN 误报仅 7.5%，适合作为第一道粗筛。
4. **后续方向**：
   - **方案四（动态条件触发）**：针对高频易错场景（工具混淆、关键槽位漏传）做定向拦截，与方案三叠加使用，降本增效（详见第六节）；
   - 压缩方案三每题的 instructions（字段说明共享化），把输入 token 从 ~3.6 万/题降下来；
   - 针对近义工具混淆类 badcase，考虑在 tool_choice 的 criteria 中强化易混工具的区分描述；
   - 扩大评测集（当前 40 badcase），验证阈值的稳健性后再上线灰度。
