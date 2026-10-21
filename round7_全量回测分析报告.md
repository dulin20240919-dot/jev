# round7 全量回测分析报告（1086 条）

> 生成日期：2026-10-20 ｜ 环境：offline（search_jev_nlp_offline）｜ 模型：jev（System One，noul 判别，th=0.25）
> 数据：data/round7/round7_full_cn.jsonl —— round6 全量 1086 条（正 1035 + 负 51）基座上，system_rules/question 替换为 round7 版（与专项集 round7_special_v7 完全同版，`from build_round7_rules import` 并逐条断言校验），其余 state 字段与 round6 逐字一致。
> 汇总：data/round7/jev_round7_全量结果汇总.xlsx（1086 条逐条明细，含 messages 列）

---

## 〇、总览：round6 → round7

| 指标 | round6 | round7 | 变化 |
|---|---|---|---|
| **acc@0.25** | 0.9328 | **0.9411** | **+0.83pp** |
| 误拦（正样本被拦） | 65（6.3%） | **54**（5.2%） | -11 |
| 漏放（负样本放行） | 8（15.7%） | **10**（19.6%） | +2 |
| 正样本 noul 均值 | 0.875 | 0.896 | +0.021 |
| 负样本 noul 均值 | 0.129 | 0.150 | margin 持平 0.746 |
| 负样本压至 <0.05 | 37/51 | 37/51 | 持平 |
| 时延 mean / p50 | 435ms | 243ms / 269ms | 本轮服务端显著更快 |
| best th | 0.05（acc 0.9512） | **0.05（acc 0.9669）** | — |

阈值扫描（round7）：

| th | 0.05 | 0.10 | 0.15 | 0.20 | **0.25** | 0.30 | 0.40 | 0.50 |
|---|---|---|---|---|---|---|---|---|
| acc | **0.9669** | 0.9530 | 0.9466 | 0.9448 | 0.9411 | 0.9392 | 0.9273 | 0.9180 |
| 误拦/漏放 | 22/14 | 37/14 | 46/12 | 48/12 | 54/10 | 56/10 | 69/10 | 80/9 |

online/train 分解：online 正 85 误拦仅 2（2.4%）；train 正 929 误拦 52（5.6%）；负样本 51 条全部来自 online，漏放 10。

**结论：round7 规则净收益 +0.83pp，专项修复全部保持、零回落；但引入 19 条正向新破坏和 4 条新漏放，其中 2 处是规则措辞直接造成的回退（详见二、三节）。**

---

## 一、逐条流动（1086 条共有样本）

| 方向 | round6 对→round7 错 | round6 错→round7 对 |
|---|---|---|
| 正向（1035） | **新破坏 19** | 修复 30（= 专项修复的 30 条，全量复跑保持） |
| 负向（51） | **新漏放 4** | 修复 2（case025 打车 0.113、case039 0.212，保持） |

专项集 73 条在 full 中结果与专项跑**完全一致**（修复 30+2 无一回落，未修 35+6 无一改变）。

---

## 二、误拦 54 = 存量未修 35 + 新破坏 19

### 2.1 存量未修 35 条

即 round7 专项报告第 1.2 节的 35 条（车控/家控"部件×功能"跨界 11、CheckWeatherIndex 2、标注惯例 3、媒体内容 4、工具形态 3、条件挂载 2、检索/设置/翻译零散 10），full 复跑 noul 与专项跑基本一致（个别 ±0.05 浮动），无新增归因。归因与 round8 建议见专项报告，此处不重复。

### 2.2 新破坏 19 条（round6 放行 → round7 拦下）——本轮重点

**A. StartSport / CreateAlarm 家族（4 条，心智模型扩大误伤）**

| case | query | 工具 | r6 → r7 |
|---|---|---|---|
| case117 | 开启运动 | StartSport | 0.997 → **0.024** |
| case470 | 开始探险 | StartSport | 0.887 → 0.133 |
| case567 | 每天偶数点50分提醒喝水 | CreateAlarm | 0.693 → 0.245 |
| case838 | 舅舅生日闹钟提醒买礼物 | CreateAlarm | 0.860 → 0.133 |

round6 里 jev 只是不认"单板/高尔夫球场"是运动（case797/740 拦下）；round7 规则后**连直白的"开启运动"“开始探险”都不认了**（0.997→0.024 是全表最大跌幅）。CreateAlarm 同理：r6 一直不认 case249（纪念日买礼物），r7 又多拦了 case567/838 两条"闹钟提醒"。jev 的心智模型是"提醒→Reminder、闹钟→只在用户明说'闹钟'时"，与语料惯例（提醒/闹钟混用 CreateAlarm）冲突面在扩大，**不再是单点问题而是 7 条的家族问题**（存量 3 + 新破坏 4）。

**B. 车控 CarMode / CarDeviceFunction / 驾驶辅助（5 条）**

| case | query | 工具 | r6 → r7 |
|---|---|---|---|
| case365 | 优先纯电关上 | UnsetCarMode | 0.531 → 0.058 |
| case399 | 关掉女王座驾模式 | TurnOffCarDeviceFunction | 0.423 → 0.156 |
| case483 | 打开高度自动调节 | TurnOnCarDeviceFunction | 0.798 → 0.126 |
| case618 | 开启全景 | SetDriverAssistance | 0.881 → 0.123 |
| case822 | 车内PM2.5中度时温控箱35度 | Pm25StateEvent+SetCarDeviceTemperature | 0.378 → 0.202 |

与存量 A 类（部件×功能跨界）同根，但**这 5 条 r6 本来是放行的**——规则 6 的车控 Event 点名 + 规则 2 的车控锚例收窄了 jev 对"XX模式""XX调节"的容忍度，反而把边缘放行条压到了线下。case822 尤其值得注意：同型 case824（CarStateEvent 挂风速）拿到 1.000，Pm25StateEvent 挂温控却 0.202——条件挂载条款对非点名的 Pm25StateEvent 不生效。

**C. 高分跌落的功能词/模糊指代（10 条）**

| case | query | 工具 | r6 → r7 |
|---|---|---|---|
| case300 | 帮我下一个滴滴送货 | DownloadApp | 0.915 → 0.003 |
| case205 | 于翔电话 | CheckContact | 0.920 → 0.223 |
| case930 | 开我的灯光 | TurnOnSmarthomeDevice | 0.928 → 0.228 |
| case870 | 小窗帘开着吗 | CheckSmarthomeDeviceSwitchStatus | 0.294 → 0.095 |
| case285 | 下载 | SaveImage | 0.281 → 0.016 |
| case021 | 打开全天眼部舒适功能 | TurnOnEyecomfort | 0.407 → 0.015 |
| case191 | 导航去第三个 | Navigate | 0.693 → 0.133 |
| case606 | 调成1：1 | Select | 0.743 → 0.202 |
| case767 | 仪表设置为地图 | SetThemes | 0.637 → 0.126 |
| case081 | 找橙子拿铁的咖啡店 | SearchCate | 0.294 → 0.202 |

共性：**模糊指代（"下载"承前文、"导航去第三个"承卡片、"开我的灯光"）和功能别名（"眼部舒适"=护眼、"全景"=全景影像、"仪表设置为地图"=主题）**。规则 4 要求"结合前文"反而让 jev 更积极地去找"更该做的事"，把原本靠字面惯性放行的条目重新审视后拦下。这部分一半是新规则副作用、一半是这些条 r6 时本就在 0.3-0.5 的悬崖边。

**小结**：19 条新破坏里，A 类 4 条是明确的心智模型冲突扩大；B 类 5 条是车控条款的双刃剑；C 类 10 条多为悬崖边条目的自然波动叠加规则收紧。**round8 最优先**：给 StartSport/CreateAlarm 家族加正向锚例（"用户说运动、探险、开始锻炼，用 StartSport 是对的；说提醒/闹钟，CreateAlarm 和 CreateReminder 都是对的"），这一条预计可回收 7 条（存量 3 + 新破坏 4）。

---

## 三、漏放 10 = 存量未修 6 + 新漏放 4

### 3.1 存量未修 6 条

case037（不要扫一扫 0.899 不动）、case077（NFC钱包 0.932）、case067（方向词 0.743）、case071（黑屏 0.731）、case061/081（0.500）。归因见专项报告第二节——jev 对否定/应用vs设置/方向词敏感度不足，连续两轮点名无效，不再投入。

### 3.2 新漏放 4 条（round6 拦下 → round7 放行）——**两处规则性回退**

| case | query | 被审核输出 | r6 → r7 | 回退原因 |
|---|---|---|---|---|
| **case009** | 打开华为分享 | OpenApp | 0.085 → **0.469** | **规则 3 直接回退**："Translate、Call 这类工具本身就做这件事，候选里还有 LaunchTranslationTool、CallBack 等，也不算错"的句式被泛化，连"打开华为分享用 OpenApp 而候选有 TurnOnHuaweiShare"这个规则 3 自己举的反例都放走了（该反例写在 criteria.false 里，但 criteria.true 的宽表述压过了它） |
| **case032** | 拍照翻译 | LaunchTranslationTool | 0.004 → 0.577 | 同上——"候选里有 LaunchTranslationTool 不算错"本意是豁免被调的 Translate，但这里被调的就是 LaunchTranslationTool，语料判定它错（应拍照+翻译组合），规则句式无法区分"被调"和"候选"方向的豁免 |
| case065 | 对准二维码自动打开支付宝设置一下 | ScanCode | 0.202 → 0.706 | "设置一下"表述被当成了设置项意图的一部分，ScanCode 的 description 沾边即放 |
| case070 | 打开熄屏录音功能 | StartRecording | 0.173 → 0.637 | "熄屏录音"作为复合功能词被 description 覆盖判对；语料判错（该用组合调用） |

**判断**：case009 是最刺眼的一条——华为分享反例从 v6c 到 round6 一直拦得住（0.085），round7 规则把它放走了，这是**规则文本明确引入的回退**。case032 同理。这两条必须在 round8 修规则措辞：把"Translate、Call……也不算错"收窄为**只豁免被调工具是 Translate/Call 本身**的场景（"被调的是 Translate、Call 时，候选里有 LaunchTranslationTool、CallBack 不算它错"），不豁免反向（被调 OpenApp/LaunchTranslationTool 而候选有更专门的）。case065/070 属 description 覆盖判定的边界，与存量 case061/081 同型，归入能力边界。

---

## 四、round8 规则修订清单（按预期回收排序）

1. **StartSport / CreateAlarm 正向锚例**（回收约 7 条：新破坏 4 + 存量 3）："用户说运动、锻炼、探险、开始某项活动，用 StartSport 是对的；说提醒我/闹钟，CreateAlarm 和 CreateReminder 都是对的，不要求区分。"——针对当前最大误拦家族。
2. **华为分享反例恢复 + 豁免方向收窄**（回收 case009/032，防再犯）：规则 3 改写为"被调的是 Translate、Call 本身时，候选里有 LaunchTranslationTool、CallBack 不算选错；**反过来，被调的是 OpenApp、LaunchTranslationTool 这类泛化工具，而候选里有 TurnOnHuaweiShare、Translate 这类更专门的工具时，算选错**"。
3. **车控/家控"部件×功能"宽对位**（回收存量 A 类 11 条的大部 + 防止 B 类继续扩大）："车控和智能家居里，部件（车窗、座椅、头枕、冷柜、新风等）和功能（亮度、高度、角度、温度、模式开关）的组合，只要工具的 description 提到该部件或该功能之一，就算能做到。"
4. **Pm25StateEvent 等条件挂载泛化**（回收 case822，加固 case810/821）：规则 6 的"等各种 Event"扩展明确点名 Pm25StateEvent 及其他状态类 Event。
5. **模糊指代容忍**（回收 C 类部分）："用户用'下载''开灯''导航去第三个'这类短指代承前文或卡片时，用承接前文意图的工具是对的。"

其余（媒体承接词、反向说法补全、查询配设置工具容忍等专项报告建议）优先级不变。

### 不再投入的方向

- case037（用户否定）、case077（应用vs设置）、case067（方向词）、case071（字面相似）、case061/081（description 沾边）、case065/070（同型）：连续多轮规则点名无效或属能力边界；
- case249（CreateAlarm 惯例冲突）单独一条不再打，并入第 1 条锚例统一处理。

---

## 五、数据口径

- 输入：data/round7/round7_full_cn.jsonl（1086 条；round6_tool_only_cn.jsonl 基座，规则/question 为 round7 版，与专项集同版；构建脚本 build_round7_full_rules.py，逐条断言 state 其余字段与 round6 逐字一致）。
- 批跑：单线程 offline，1086 条全部成功；结果 data/round7/round7_full_cn_result.jsonl。
- 汇总：data/round7/jev_round7_全量结果汇总.xlsx。
- 判定口径：th=0.25；误拦 = label True 且 noul<0.25；漏放 = label False 且 noul≥0.25。
- 本报告全部 noul 数值均已与结果文件逐条核对一致；与 round6 的对比基于同 orig_id 对齐。
