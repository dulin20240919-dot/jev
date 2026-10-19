# jev 模型调用项目

本项目是对 **jev 模型** 的调用尝试，基于 `search_jev使用文档.md`（内部使用文档）与 `jev官方文档.md`（来自 https://docs.typesafe.ai 的官方文档）整理而成，包含：

- `jev_predict_common.py` — 封装好的带签名的 `/predict` 公共请求模块
- `jev_client.py` — 命令行调用脚本（内置天气 / 网页重排两个示例，支持自定义 payload）
- `README.md` — 本文档

---

## 1. jev 模型是什么（含官方文档详解）

> 本节综合了 `jev官方文档.md`（来源 https://docs.typesafe.ai ，含 Introduction / System One / State / Primitives / Choice / Score / Noul / Advanced: structure / Confidence 全部页面）与内部使用文档 `search_jev使用文档.md`。这些信息用于后续方案设计。

### 1.1 概述

jev 是 **TypeSafe 公司的旗舰模型**，也是第一个 **System One** 模型。它是一个**结构化判别/打分模型**，不是生成式对话模型（实测内网网关返回 `output_tokens: 0`，纯判别式）：

- 名称源自 Kahneman《思考，快与慢》中的 **System 1**——专为「快速结构化决策」设计：每个问题只要求一个几秒钟的直觉判断
- **不生成文本**，只返回**类型化答案 + 概率分布 + confidence**
- 使用方式：
  1. 给它一段 `state`（上下文状态，比如天气描述，或「query + 网页文档」组合）
  2. 针对这段 state 提出**一组问题**（`questions`），每个问题声明自己的类型和判定标准（`criteria`）
  3. 模型按标准返回**结构化的判定结果**（是/否概率、选项分布、等级分数），而不是自由文本

三种问题类型（`type`，官方称 primitives）：

| type | 含义 | criteria 形式 | 返回字段 | 典型用途 |
|------|------|--------------|---------|---------|
| `noul` | 是非判断 | `{"true": "会下雨", "false": "不会下雨"}` — 描述真/假两种情形（可选） | `noul`（=yes 概率 0~1，无 confidence） | 判断某事实是否成立 |
| `choice` | 单选（无序选项） | `{"sunny": "晴天，无降雨", ...}` — key 是选项名，value 是选项描述；最多 255 个选项 | `choice` + `probabilities` + `confidence` | 从若干类别中选一个 |
| `score` | 等级评分（有序谱） | `["无降雨", "小雨", "中雨", "大雨"]` — 有序数组，2~10 个等级，第 i 项代表等级 i | `score` + `legend` + `probabilities` + `confidence` | 0 到 N-1 的程度打分，如搜索相关性 0-9 分 |

**主要业务场景**（见示例）：

- **rerank 网页重排**：state 放 query + 网页（title / chunk / 站点 / 发布时间 / 标题匹配度等），用 `score` 型问题对文档回答 query 的「帮助程度」打 0-9 分，用于搜索结果重排。评分指令强调：先判相关性，再按 query 实际需要考虑时效性与权威性，时效/权威不能弥补相关性不足。
- **天气示例**：演示一次请求同时提 noul / choice / score 三种类型的问题。

底层等价性：payload 中 `data` 字段与 jev 的 `https://api.typesafe.ai/v1/systemone` 请求体**完全相同**，本服务只是在其外层套了一层网关签名（CLOUDSOA-HMAC-SHA256）。内网网关返回结构与官方 API 一致（`answers` 下按问题 ID 返回 type / probabilities / confidence / legend 等）。

### 1.2 System One 核心机制（方案设计必读）

1. **所有问题并行、独立评估**。一次请求中的问题互不作为上下文（无 context-rot），加问题几乎不增加响应时间。官方数据：13 个问题批在一次请求里，比 13 次单独调用**便宜 11.5 倍、快 9.6 倍**。
2. **原子问题原则**：每个问题只问一个「几秒钟的直觉判断」。复杂判断拆成多个问题，在**代码中**加权组合。例：「客户是否愤怒且要求退款」要拆成两个 noul。
3. **Composite scoring（组合打分）**：多个 score 问题的答案在代码中组合前，先**归一化**（`score ÷ 最高等级号`），再按业务权重加权求和。
4. **Speculative fan-out（投机性并发提问）**：把可能需要的问题都放进同一次请求，代码忽略用不到的答案——反正几乎不增加成本。
5. **只有问题间存在真实依赖时才发起第二次请求**（例：分类树逐层下钻），这是例外而非常规。
6. **问题 ID 不会发给模型**——模型看到的只有 instructions 和 criteria，所以完整问题必须写进 `instructions`。

### 1.3 State（上下文状态）设计

- `state` 可以是**字符串 / JSON 对象 / 数组**；多数场景建议用**对象**（字段有描述性名称，模型能理解结构）
- `instructions` 中可以用**反引号包裹的点-下标路径**引用 state 字段，如 `` `ticket.messages[0].text` ``、`` `resume.experience` ``
- 结构化数据（schema、taxonomy、数据库行）直接作为 JSON 传入，**不要**序列化成字符串模板

### 1.4 Choice 详解

- 从固定选项集中单选；`criteria` 是 map（选项名 → 描述），**最多 255 个选项**
- 返回：`choice`（最高概率选项）、`probabilities`（全选项分布，和为 1）、`confidence`（0~1，见 §1.7）
- 选项是**无序**的；建议加 `other` / `none of the above` 兜底选项
- **结构化选项描述**：选项 value 可为对象，字段名自选（如 `what` / `not_for` / `examples`，字段名不会保留）。写清「该选项**不**覆盖什么」能锐化选项边界。例子必须像真实输入才有效。
- **深度分类（taxonomy walk）**：对深层分类树，每层问一个 Choice，选项为当前节点的子节点、选项值为各自的子树（让模型看到分支下有什么再决定），代码循环下钻直到叶子。分支过大时裁剪为直接子节点 + 叶子采样。概率接近时可保留多条候选路径（beam search）。

### 1.5 Score 详解

- 按有序等级量表评分；`criteria` 是**有序数组**，**2~10 个等级**
- 返回：`score`（等级谱上的位置，**可为小数**，= Σ 等级号 × 该等级概率 的加权和）、`legend`（等级号 → 描述映射）、`probabilities`、`confidence`
- **等级编写原则**（重要）：
  - **描述情境而非程度**——「有替代方案的故障」好于「中等严重」
  - 模型**看不到等级编号，也看不到相邻等级**，每个等级描述必须独立可判
  - 每个 score 问题只测**一个维度**；多维度拆多问 + Composite scoring
- **结构化等级**：数组每项可为对象（如 `summary` + `signals` 字段，字段名自选）

### 1.6 Noul 详解

- 是非判断；返回 `noul`（「是」的概率 0~1），**无单独 confidence**（只有 yes/no 两个结局，单值即完备；如需与 Choice 同尺度，可用 `|2p − 1|`）
- 数值含义：接近 1 = 强 yes，接近 0 = 强 no，接近 0.5 = 模型对 yes/no 概率相近
- **编写原则**：
  - 一个 noul 只问**一个**是/否问题；复合条件拆多问，代码组合
  - 措辞让**高值 = yes**（「消息是否包含个人数据」清晰；「是否不含个人数据」会让后续读代码的人搞反）
  - 陈述句与疑问句效果相当，可用自己的数据试两种措辞
  - 让边界无歧义：「有任何 Python 经验吗」的 "any" 不留中间地带；边界微妙时加 `criteria.true` / `criteria.false`（多数情况 instructions 就够，两种都试试）
- **noul 不是程度量表**：问「程度」用 score。noul 只判断一个命题为真的概率，中间值可能意味着「中等程度」也可能意味着「案例不清」，间距也不是你定义的
- **阈值设计**（在代码里做）：0.5 = yes/no 行动代价相同时用；误报代价高（如自动退款、打电话叫人）→ 调高；漏报代价高（如安全漏标）→ 调低；**中间值送人工**（三段式，与 confidence 三档模式一致）
- **直接用概率排序**：rerank 场景官方做法是每个 query-候选对一个 noul，**按概率值排序**而非设阈值
- **结构化 instructions**：问题文本固定放一个字段（如 `question`），每个候选的数据放其他字段（如 `potential_duplicate`），一次请求批量判重——问题 key 可带数据库 ID

### 1.7 Confidence（置信度）

每个 Choice / Score 答案都带 `confidence`（0~1），由 `probabilities` 的**分布形状**推导：全概率集中在一个结果 = 1，均匀铺开 = 0。

**三档使用模式**（在代码中）：

| 档位 | 行为 |
|------|------|
| 高 confidence | **自动执行**，无需人工介入 |
| 中 confidence | **谨慎执行**：请用户确认 / 标记审核 / 先收集更多信息 |
| 低 confidence | **不执行**：转人工 / 请求澄清 / 回退到其他系统 |

**阈值随风险缩放**：同一系统内不同动作门槛不同。官方示例：0.5 作为「模型真不确定」的下限，低于即转人工；只读操作（查余额）0.5 以上即可执行；破坏性操作（批准转账）要 >0.9 才自动执行，否则请用户二次确认。**从保守阈值起步，用自己的数据测试后再调。**

**计算公式**（可自行从 `probabilities` 复算或改用其他度量）：

- Noul：无 confidence；等价物 `|2p − 1|`
- Choice（n 个选项，p_max 为最高概率）：`(p_max − 1/n) / (1 − 1/n)` — 只看最高概率超出均匀分布的程度
- Score（等级有序）：`1 − 概率加权离峰距离 ÷ 均匀分布平均距离` — 概率落在**相邻**等级降 confidence 较少，落在**远处**等级降得多（Choice 公式不区分远近）
- 实用替代度量：**top probability**（p_max 本身，阈值需按选项数逐问题定）、**top-to-second ratio**（p_max / p_second，衡量头名对次名的优势，适合二选一决策）

**概率校准**：System One 模型的概率**针对结果校准**，但校准以**预测组**衡量，不保证任何单次答案正确。

### 1.8 重要限制与语言问题（方案设计必须考虑）

- **仅接受文本输入**：不支持图片 / 音频 / 视频
- **主要训练语言是英语**：中文等 CJK 语言可以接受，但**准确率较低**。做中文方案时的应对思路：
  - `instructions` / `criteria` / 等级与选项描述**尽量用英语写**（模型对英语 rubric 理解最好）
  - state 中的中文内容可以保留（模型能读），但需用自己的数据验证效果
  - 阈值设置更保守，把更多中间值送人工/二次校验
  - 上线前用真实中文数据做准确率评估
- 官方资源：Python SDK `typesafe-sdk`、JS/TS SDK `@typesafe-ai/sdk`、云端 API `POST https://api.typesafe.ai/v1/systemone`（Bearer 鉴权）、文档索引 https://docs.typesafe.ai/llms.txt 、Claude Code agent skill（`claude plugin marketplace add typesafe-ai/skills`）
- 官方 cookbook 中与本项目相关的模式：**Re-ranking**（每对一个 noul、按概率排序）、**Parallel questions**（单请求 13 问监管清单）、**Hierarchical classification**（分类树逐层下钻 + beam search）、**Self-consistency**（多次运行测 noul 稳定性）

> **性能提示**：目前推理性能未优化，近期会升级成 vllm 引擎，**请求方式不变**。

---

## 2. 请求结构与签名机制

### 2.1 完整 payload 结构

```json
{
  "version": "1.0",
  "meta": {
    "bId": "search_jev_nlp_test",
    "flowId": "search_jev_nlp_test",
    "uuId": "毫秒时间戳字符串"
  },
  "data": {
    "model": "jev-latest",
    "state": "...",
    "questions": {
      "问题名": {
        "type": "noul | choice | score",
        "instructions": "问题指令",
        "criteria": "..."
      }
    }
  }
}
```

要点：

- `meta`（bId / flowId / uuId）会被拼接到请求 URL 的 query string 上，**不进 body**
- `data` 走 JSON body，与 systemone 请求体相同
- `bId` / `flowId` 填对应环境的 SERVICE_NAME（见 §4 环境配置）

### 2.2 签名方式（CLOUDSOA-HMAC-SHA256）

`jev_predict_common.py` 中的 `send_predict` 已完整实现，流程：

1. 把 `meta` 合并进 URL query，序列化为 `query_string`；body 为 `data` 的 JSON
2. 取毫秒级 `timestamp`
3. 构造签名字符串：`POST&{path}&{query_string}&{body}&appid={app_id}&timestamp={timestamp}`
4. 用 `SIGN_KEY` 做 HMAC-SHA256，结果 base64 编码得到 `signature`
5. 请求头：

```
Content-Type: application/json
Authorization: CLOUDSOA-HMAC-SHA256 appid={app_id}, timestamp={timestamp}, signature="{signature}"
```

### 2.3 环境变量（均可覆盖默认值）

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SEARCH_JEV_SERVICE_URL` | `http://10.41.1.17:8080/predict` | 服务地址 |
| `SEARCH_JEV_APP_ID` | `search_jev_nlp_test` | appid |
| `SEARCH_JEV_SIGN_KEY` | `71C956 | 签名密钥 |
| `SEARCH_JEV_MODEL` | `jev-latest` | 模型名 |
| `SEARCH_JEV_SERVICE_NAME` | `search_jev_nlp_test` | bId / flowId 用（jev_client.py） |

### 2.4 响应体结构注意（重要）

> **使用 vllm 大模型服务部署后，返回体少了最外层包装，业务侧对接需注意。**

两种返回体形态对比（以 noul 问题为例）：

**有最外层包装（当前老引擎）：**

```json
{
  "code": 0,
  "data": {
    "model": "jev-latest",
    "answers": {
      "rain": {
        "type": "noul",
        "noul": 0.99
      }
    },
    "usage": { "input_tokens": 360, "output_tokens": 0 }
  }
}
```

**无最外层包装（vllm 引擎部署后）：**

```json
{
  "model": "jev-latest",
  "answers": {
    "rain": {
      "type": "noul",
      "noul": 0.99
    }
  },
  "usage": { "input_tokens": 360, "output_tokens": 0 }
}
```

即：老引擎的 `answers` / `usage` 在 `data` 字段下，vllm 后直接在顶层。业务侧解析时需兼容两种形态（本项目的 `run_jev_eval.py` 已做兼容：先取 `data.answers`，取不到再取顶层 `answers`）。

---

## 3. 脚本使用方法

依赖：`pip install requests`

### 3.1 运行内置示例

```bash
# 天气示例：一次请求包含 noul / choice / score 三种问题类型
python jev_client.py weather

# 网页重排示例：对 (query, document) 打 0-9 帮助程度分
python jev_client.py rerank
```

### 3.2 自定义请求

**方式 A：只写 `data` 字段**（脚本自动补 version / meta）：

```bash
python jev_client.py file --payload my_data.json
```

`my_data.json` 示例：

```json
{
  "model": "jev-latest",
  "state": "你的上下文内容……",
  "questions": {
    "my_question": {
      "type": "choice",
      "instructions": "你的问题",
      "criteria": {
        "option_a": "选项 A 的描述",
        "option_b": "选项 B 的描述"
      }
    }
  }
}
```

**方式 B：完整 payload**（含 meta，脚本原样发送）：

```bash
python jev_client.py raw --file full_payload.json
```

### 3.3 切换环境（offline / prod）

**offline 环境**：SERVICE_NAME 换为 `search_jev_nlp_offline`，且**服务地址不同**（`http://10.97.134.97:8123/predict`），调用时需显式传 url：

```python
from jev_predict_common import send_predict

SERVICE_NAME = "search_jev_nlp_offline"

result = send_predict(
    payload,
    url="http://10.97.134.97:8123/predict",
)
```

用环境变量的等效写法：

```bash
# offline
export SEARCH_JEV_SERVICE_URL=http://10.97.134.97:8123/predict
export SEARCH_JEV_SERVICE_NAME=search_jev_nlp_offline
# prod
export SEARCH_JEV_SERVICE_NAME=search_jev_nlp_prod
```

### 3.4 在自己代码中调用（test 镜像环境）

```python
import json
import time
from jev_predict_common import send_predict

payload = {
    "version": "1.0",
    "meta": {
        "bId": "search_jev_nlp_test",
        "flowId": "search_jev_nlp_test",
        "uuId": str(int(time.time() * 1000)),
    },
    "data": {
        "model": "jev-latest",
        "state": "今天乌云密布，天气预报显示下午有中雨。",
        "questions": {
            "rain": {
                "type": "noul",
                "instructions": "今天会下雨吗？",
                "criteria": {"true": "会下雨", "false": "不会下雨"},
            }
        },
    },
}
result = send_predict(payload)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

> **response body 注意！！！**：使用 vllm 大模型服务部署后，返回体**少了最外层包装**（`code`/`data` 包装层），业务侧对接需注意——详见 §2.4。

---

## 4. 环境与鉴权（关键信息，勿丢）

| 环境 | SERVICE_NAME（bId / flowId） | 服务地址 |
|------|------------------------------|---------|
| test（默认） | `search_jev_nlp_test` | `http://10.41.1.17:8080/predict` |
| offline | `search_jev_nlp_offline` | `http://10.97.134.97:8123/predict` |
| online/prod | `search_jev_nlp_prod` | （同此前线上 /predict 接口的 ip、端口） |

- **offline 与 online 的 appID、sign_key** 和之前在 online 或 offline 调用的 `/predict` 接口相同
- **各个业务使用自己的 appID、SIGN_KEY**（即上表 SERVICE_NAME 只影响 bId/flowId，鉴权凭据各业务自备）
- **响应体注意**：vllm 部署后返回体少最外层包装（见 §2.4）

---

## 5. rerank 评分标准（0-9 帮助程度）

来自 rerank 示例，可直接复用：

| 分值 | 含义 |
|------|------|
| 0 | 完全无关，对回答、理解或完成查询没有任何帮助 |
| 1 | 仅有偶然词面重合，主题或用户意图不匹配 |
| 2 | 与宽泛主题略有关联，但基本不能帮助满足查询 |
| 3 | 涉及相关主题，但明显偏离主要意图或实用信息很少 |
| 4 | 有一定实质帮助，但存在明显意图偏差、信息缺失或质量问题 |
| 5 | 中等相关，能够部分满足主要意图，但不够直接或完整 |
| 6 | 较相关，对主要意图有明显帮助，但仍有重要缺口 |
| 7 | 高度相关，能较好满足主要意图，只有少量缺失或局限 |
| 8 | 非常相关、准确且充分；若查询需要时效或权威，相关要求也基本满足 |
| 9 | 直接、准确、完整且权威地满足查询，是极佳结果 |

评分原则：先识别 query 的主要用户意图，判断内容是否直接相关、准确且有用；**只有在 document 已经相关的前提下**，才按 query 的实际需要考虑时效性和来源权威可靠性——需要时越新或越权威越好，不需要时不要机械降分；**时效性和权威性不能弥补相关性不足**。

rerank 示例的 `state` 可携带的文档字段（供参考）：

| 字段 | 含义 |
|------|------|
| `query` | 用户搜索词 |
| `current_time` | 当前日期（如 `2026年08月27日`） |
| `title` | 网页标题 |
| `chunk` | 网页正文片段 |
| `site_name` / `site` | 站点名 / 域名 |
| `publish_time` / `publish_age_days` | 发布时间 / 距今天数 |
| `match_title_ratio` | 标题与 query 的匹配度 |

---

## 6. 其他说明

- 「镜像环境」指 test 环境（`search_jev_nlp_test`，ip `10.41.1.17:8080`）
- 「其余业务参考使用示例」——其他业务场景按 weather / rerank 的结构，替换 `state` 与 `questions` 即可
- 后续 vllm 引擎升级后**请求方式不变**，业务侧无需改动
