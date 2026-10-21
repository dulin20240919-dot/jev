# round7 专项优化分析报告 — 误拦/漏放 73 条修复情况

> 生成日期：2026-10-20 ｜ 环境：offline（search_jev_nlp_offline）｜ 模型：jev（System One，noul 判别，th=0.25）
> 专项集：round6 遗留的误拦 65 条（正样本）+ 漏放 8 条（负样本），共 73 条。
> 改动：system_rules / question 全局替换为 round7 版（6 条规则，按 round6 报告的 6 条建议修订）；state 其余字段不变。
> 目标定义：误拦条 noul≥0.25 即修复（放行）；漏放条 noul<0.25 即修复（拦下）。

---

## 〇、总览

| 类别 | 条数 | 修复 | 修复率 | 未修复 |
|---|---|---|---|---|
| 误拦（label=True） | 65 | **30** | 46.2% | 35 |
| 漏放（label=False） | 8 | **2** | 25.0% | 6 |
| 合计 | 73 | **32** | 43.8% | 41 |

时延 mean 473ms（与 round6 全量 435ms 同量级，规则加长影响不大）。

注意：本集是**只含 round6 错误条目的专项集**，修复率不能直接外推全量 acc；round7 规则定型后需回测 round6 全量 1086 条确认无新破坏。

---

## 一、误拦 65 条：修复 30 / 未修复 35

### 1.1 修复的 30 条（按病灶类分组，noul 均已过 0.25）

**设置项查询（5 条，CheckSetting 类全清）**——"通用设置工具能处理用户说的设置项时就算选对，候选里有更专门的也一样"直接命中：

| case | query | 工具 | r7 noul |
|---|---|---|---|
| case107 | 显示一下流量排行 | CheckSetting | 0.665 |
| case108 | 查一下流量排行 | CheckSetting | 0.777 |
| case112 | 查显示刷新频率 | CheckSetting | 0.844 |
| case117 | 锁屏语音技能状态 | CheckSetting | 0.950 |
| case101 | 色彩校正功能状态 | CheckSetting | 0.982 |

**CardOperation 决策类（4 条全清）**——"从屏幕列表/卡片选第几项用 CardOperation 是对的，即使之后还要导航或搜索"：

case311（0.693）、case314（0.547）、case315（0.562）、case940（0.920）。

**前文承接/提醒类（3 条）**——"9点"式承接锚例生效：

case054「9点」续接前文提醒（0.469）、case341「9:30叫我」（0.593）、case659 每天下午6点打 welink 卡任务（0.835），均 CreateReminder。

**语义映射/反向说法（7 条）**——"Translate、Call 本身做这件事时，候选里的 LaunchTranslationTool、CallBack 不算更专门"+"反向说法也算对上"：

| case | query | 工具 | r7 noul |
|---|---|---|---|
| case199 | 打开静音 | TurnOnQuietMode | 0.963 |
| case279 | 打开导航声音 | TurnOffQuietMode | 0.453 |
| case868 | 打开英译中翻译 | Translate | 0.577 |
| case587 | 回拨报警电话 | Call | 0.407 |
| case710 | 全屋音乐换上一首 | PreviousMedia | 0.294 |
| case847 | 你是不是想冻死我 | TurnUpCarDeviceTemperature | 0.531 |
| case793 | 找主题公园并导航 | Navigate | 0.307 |

**车控部件类（8 条）**——"车窗升降→高度、开亮→亮度、座椅旋转→角度"锚例部分生效：

| case | query | 工具 | r7 noul |
|---|---|---|---|
| case385 | 打开行李箱 | TurnOnCarDevice | 0.991 |
| case442 | 车窗降下来一些 | TurnDownCarDeviceHeight | 0.438 |
| case459 | 降一点三排车窗 | TurnDownCarDeviceHeight | 0.363 |
| case999 | 二排左座椅旋转0度 | TurnUpCarDeviceAngle | 0.731 |
| case462 | 把空调锁禁用了 | UnlockCarDevice | 0.798 |
| case541 | 打开智能调节远光灯 | TurnOnCarSetting | 0.910 |
| case531 | 关闭(后座)安全带提醒 | TurnOffCarSetting | 0.407 |
| case628 | 关掉（承接前文车控） | TurnOffCarSetting | 0.349 |

**决策工具（1 条）**：case332 Confirm（0.321）。

**车控条件挂载（2 条）**——规则 6 点名 CarcontrolSwitchEvent / CarStateEvent 生效：

case824「车内24度时风速最大」CarStateEvent+SetCarDeviceWindspeed（1.000）、case826「二排关车窗时开驱动模式」CarcontrolSwitchEvent+TurnOnCarSetting（0.294）。

### 1.2 未修复的 35 条（noul 仍 <0.25），按形态归 7 类

**A. 车控/家控"部件×功能"跨界（11 条，最大残留簇）**

| case | query → 工具 | r7 noul | 症结 |
|---|---|---|---|
| case931 | 隐私车窗开亮一点 → TurnUpCarDeviceLuminance | 0.020 | jev 不认"车窗有亮度"（隐私玻璃调透光） |
| case760 | 调高背门玻璃亮度 → TurnUpCarDeviceLuminance | 0.101 | 同上 |
| case918 | 打开卧室冷暖新风 → TurnOnSmarthomeDevice | 0.001 | "新风"与"设备"词面差 |
| case617 | 调整肩枕声音的模式 → TurnOnCarDeviceFunction | 0.129 | 部件(头枕)×功能(声音)跨位 |
| case643 | 关冷柜保鲜模式 → TurnOffCarDeviceFunction | 0.095 | "保鲜"≈"制冷"存疑 |
| case599 | 关后座安全带提醒 → TurnOffCarSetting | 0.140 | 同型 case531 已修，本条仍拦 |
| case526 | 关卫士模式 → TurnOffCarScene | 0.043 | "Scene"形态 vs "Setting"直觉 |
| case776 | 起伏脱困 → SetDriveMode | 0.031 | 场景词→驾驶模式推理链 |
| case932 | 关自动启停 → UnsetDriveMode | 0.003 | "启停"vs"驻车/驾驶模式"词面差 |
| case882 | 关掉看书地方的灯 → TurnOffSmarthomeDevice | 0.066 | "看书地方"→书房推理链 |
| case060 | 主卧（承接前文调温）→ SetSmarthomeDeviceTemperature | 0.002 | 规则 4 写了"主卧"锚例仍未救回 |

**B. 天气/指数查询（2 条）**：case264 上海交通指数（0.003）、case230 深圳北屋小镇（0.182）——CheckWeatherIndex 被判"不如候选 CheckWeather 直接"。规则 3 只写了"名字更像不算选错"，没覆盖"被调工具更细分、候选更泛化"的判法。

**C. 语料标注惯例 vs 常识（3 条）**：case249 纪念日买礼物→CreateAlarm（0.000，与 round6 完全持平，jev 坚持该用 Reminder）、case797 启动单板→StartSport（0.001）、case740 高尔夫球场模式→StartSport（0.052）。jev 不认为"单板/高尔夫球场"是运动，属标注惯例冲突，规则修不动。

**D. 媒体/内容意图（4 条）**：case747「换一个呗」→SwitchMedia（0.011，承接前文媒体内容的意图没被识别）、case778「播放」→ResumeMedia（0.093）、case506 播报"我需要一个闹钟"→BroadcastContent（0.057，jev 把播报文本里的"闹钟"当成了意图）、case948 关语音导航→TurnOnQuietMode（0.057，反向说法锚例只有"导航声音"一例，同型的"关播报用开静音"没救回）。

**E. 工具形态/平台归属（3 条）**：case325/326 打开屏幕链接→OpenWebsite（0.008/0.095，候选无浏览器类，疑似认为该用 OpenApp）；case865 SetRoutePreference（0.006，v6c 时 0.766 高分，round6/round7 连续两轮≈0，异常突变点，建议单独排查该条 state）。

**F. 条件挂载（2 条）**：case810 妈妈生日前一天播报→BroadcastContent+TimeEvent（0.053）、case821 左转向灯熄灭关双闪→CarcontrolSwitchEvent+TurnOffCarDevice（0.090）——同型 case826 已修，这两条仍拦，条件挂载条款修复不稳定。

**G. 检索/设置/翻译零散（10 条）**：

| case | query → 工具 | r7 noul |
|---|---|---|
| case419 | 使用网络设置时间日期 → TurnOnSetting | 0.042 |
| case421 | 想知道上网速度 → TurnOnSetting | 0.043 |
| case488 | 切换到护眼色温 → TurnOnEyecomfort | 0.024 |
| case453 | 我要会议翻译 → Translate | 0.049 |
| case961 | 用英文读一下墨镜 → Translate | 0.031 |
| case310 | 找最近的咖啡店 → SearchCate | 0.036 |
| case559 | 搜索云盘文件 → SearchFile | 0.076 |
| case348 | 打开京东扫码 → ScanCode | 0.055 |
| case040 | 关畅连陌生人消息开关 → TurnOffBlockSettings | 0.080 |
| case501 | 导航去接王明明 → Navigate | 0.017 |

其中 **case419/421 值得注意**：规则 3 已写"通用设置工具 CheckSetting/SetSetting/TurnOnSetting/TurnOffSetting 能处理就算对"，CheckSetting 5 条全清，但 TurnOnSetting 两条（"网络设置时间"“查网速”其实是查询意图，语料却用 TurnOnSetting）没救回——jev 对"查询意图配开启工具"的组合仍判错。**Translate 3 条只修了 1 条**（case868 0.577，case453/961 仍在 0.03-0.05），同工具不同表述修复不稳定，说明边界本来就在阈值附近。

---

## 二、漏放 8 条：修复 2 / 未修复 6

| case | query | 被审核输出 | r6 → r7 | 结果 |
|---|---|---|---|---|
| **case025** | 从大栅栏街道**打的**去天安门 | Navigate(drive) | 1.000 → **0.113** | ✓ **修复**（满分漏放被"打车用导航是错的"拿下，本轮价值最大的一条） |
| case039 | 鸿蒙7是正式版吗 | CheckUpdate | 0.269 → 0.212 | ✓ 修复（贴阈过线，稳定性待回测确认） |
| case037 | **不要调用**扫一扫 | ScanCode | 0.899 → 0.899 | ✗ 纹丝不动——"明确说不要用仍然用是错的"条款写了没生效 |
| case077 | 打开NFC钱包 | TurnOnSetting(NFC) | 0.818 → 0.932 | ✗ **反向恶化**——"要打开的是应用却当成设置项"写了，jev 仍认为 NFC 钱包是设置项 |
| case067 | 播**前面**的第四集 | PreviousMedia | 0.867 → 0.743 | ✗ 微降未过线——"方向反了用 PreviousMedia"点名了这条场景，只降 0.12 |
| case071 | 黑屏 | TurnOffScreenOffDisplay | 0.777 → 0.731 | ✗ 微降——"黑屏"vs"关熄屏显示"字面相似压过语义差异 |
| case061 | (图)怎么做 | FollowVisionSteps | 0.516 → 0.500 | ✗ 贴 0.5 中位 |
| case081 | 给手机降降温 | TurnDownLuminance | 0.562 → 0.500 | ✗ 候选里确无降温工具，"description 能沾边"就放 |

**判断**：未修复 6 条中，case037/077/067 三条规则已点名对应场景但 jev 不执行（否定语义、应用vs设置、方向词的敏感度不足）；case061/081 属"description 沾边即放"的能力边界；case071 是字面相似压制。连续两轮点名无效的方向不建议再投入规则措辞。

---

## 三、round6 建议 → round7 规则 → 实际效果对照

| round6 建议 | round7 规则落点 | 效果 |
|---|---|---|
| ① 收窄"更专门"判定 | 规则3："名字更像不算选错"+通用设置/Translate/Call 锚例 | **显著**：CheckSetting 5 条全清，Translate/Call 修 case868/587；但 TurnOnSetting 2 条、Translate 2 条未救回 |
| ② 补打车/方向词反例 | 规则2 打车反例 + criteria.false 方向反例 | **半收**：case025 修复（1.000→0.113）；case067 方向词只降 0.12 未过线 |
| ③ 补车控条件工具 | 规则6："也包括 CarcontrolSwitchEvent、CarStateEvent 等各种 Event" | **生效**：case824/826 修复（含 1.000 满分）；case810/821 同型未修，修复不稳定 |
| ④ 反义映射锚例 | 规则2："要打开导航声音，用关闭静音的工具是对的" | **生效**：case279 修复（0.453）；case948 同型未修复（0.057） |
| ⑤ 用户否定条款 | 规则2："明确说了不要用仍然用是错的" | **无效**：case037 纹丝不动（0.899） |
| ⑥ 车控维度锚例 | 规则2：升降→高度、开亮→亮度、旋转→角度 | **部分**：修 8 条车控部件；残留 11 条更冷门部件功能词（新风、肩枕声音、保鲜、卫士模式、脱困、启停） |
| （新增）CardOperation 条款 | 规则5："从卡片选第几项是对的" | **生效**：4 条全清 |
| （新增）前文承接锚例 | 规则4："9点""主卧" | **半收**：case054 修复（0.469）；case060 仍拦（0.002） |

---

## 四、下一步（round8 方向）

### 规则侧还能打的（按性价比排序）

1. **"部件×功能"宽对位表述**（打 A 类 11 条的大部）：规则 2 车控锚例后追加"车控和智能家居里，部件（车窗、座椅、头枕、冷柜、新风、卫士模式等）和功能（亮度、高度、角度、温度、模式开关）的组合，只要工具的 description 提到该部件或该功能之一，就算能做到"。A 类的共性是 jev 要求部件与功能双向严格对位，而语料 gold 跨位使用是常态。
2. **"更泛化的候选不算更直接"**（打 B 类及部分 G 类）：规则 3 追加"候选工具比被调工具更泛化时（被调查指数、候选查天气；被调搜云盘文件、候选管全部文件；被调管应用内功能、候选管整个应用），不算更直接"。
3. **媒体承接词锚例**（打 D 类）：规则 2 追加"「换一个」「再来一个」「播放」承接前文媒体内容时，用切换/继续媒体的工具是对的；要播报一段文字时用播报工具是对的，文字内容里提到的东西不算用户意图"。
4. **反向说法补全**（打 case948）：规则 2 反向锚例加一例"要关闭语音播报，用开静音的工具是对的"。
5. **查询意图配设置工具容忍**（打 case419/421）：规则 2 或 3 追加"用户想知道某设置项的状态或值，语料用 TurnOnSetting 类工具去查，也是对的"。

### 规则侧打不动的（建议接受或数据侧处理）

- case249（CreateAlarm）、case797/740（StartSport）：标注惯例 vs 常识，属数据标准问题，改语料或接受；
- case037（用户否定）、case077（应用vs设置项）、case067（方向词）、case071（字面相似）：jev 语义敏感度不足，连续两轮点名无效，不再投入；
- case061/081（description 沾边即放）：判别式模型能力边界；
- case865（SetRoutePreference，v6c 0.766→r6/r7 双零）：异常突变点，建议单独排查该条 state 的候选列表是否有干扰项，不急于用规则修。

### 回测提醒

round7 规则定型后在 round6 全量 1086 条回测，重点确认三件事：修好的 30 条没有反向回落；v6c→r6 的 24 条新破坏（"候选名字更贴题面"型）是否随规则 3 收窄回填；漏放 8 条以外的其他负样本未出现新漏放。

---

## 五、数据口径

- 输入：data/round7/round7_special_v7_cn.jsonl（73 条，由 round6 结果抽取：误拦 65 + 漏放 8；state 沿用 round6 口径（tools/condition_tools 只含 name+description），仅替换 system_rules/question 为 round7 版；每条带 round6_kind / round6_noul 基线字段）。
- 批跑：单线程 offline，73 条全部成功；结果 data/round7/round7_special_v7_cn_result.jsonl。
- 汇总：data/round7/jev_round7_结果汇总.xlsx（逐条明细含 messages 与 round6_noul 基线列）。
- 判定口径：th=0.25；误拦修复 = noul≥0.25，漏放修复 = noul<0.25。
- 本报告中全部 noul 数值均已与结果文件逐条核对一致。
