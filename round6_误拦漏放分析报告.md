# round6 工具校验专项评测 — 误拦/漏放分析报告

> 生成日期：2026-10-20 ｜ 环境：offline（search_jev_nlp_offline）｜ 模型：jev（System One，noul 判别）
> 本轮口径变化：**只判工具名是否选对，不再校验参数/槽位**（业务前置：负向样本仅保留工具错误 51 条，槽位错误 40 条已剔除另存）。
> 数据：正样本 1035（现网 106 + 训练 929，model_output=gold），负样本 51（全部现网，model_output=answer）。

---

## 〇、总览与 v6c 对比

### 主工作点 th=0.25（noul ≥ th 判正确放行）

| 指标 | round6 工具校验 | round5 v6c（工具+槽位） | 变化 |
|---|---|---|---|
| 总条数 | 1086 | 1126（含 40 条槽位错负样本） | 口径不同 |
| acc | **0.9328** | 0.9139 | +0.019 |
| 误拦（正样本被拦） | 65（6.3%） | 77（6.8%） | -12 |
| 漏放（负样本放行） | 8（15.7%） | 20（22.0%） | -12 |
| 负样本 noul<0.05 | 37/51（72.5%） | — | 工具错被压得极低 |
| 时延 mean | **435ms**（p50 425 / p90 566） | 553ms | **-21%** |
| state 字符量 mean | 3371 | ~4900 | -31%（剥离 input_schema） |
| 正/负 noul 均值 | 0.875 / 0.129 | — | margin 0.746，可分性好 |

分来源：
- **现网**：正 106 误拦 2（1.9%）｜负 51 漏放 8（15.7%）
- **训练**：正 929 误拦 63（6.8%）｜负 0（槽位错已剔除，工具错 train 负样本为 0）

### 逐条流动（1086 条共有条目，v6c → round6）

| 方向 | 条数 |
|---|---|
| 正向误拦修复（v6c 拦 → r6 放行） | 36 |
| 负向漏放修复（v6c 放 → r6 拦下） | 4（case009/065/072/095） |
| **正向新破坏（v6c 放 → r6 拦下）** | **24** |
| 负向新破坏（v6c 拦 → r6 放行） | 2（case025/037） |

误拦 65 条中 41 条 v6c 也误拦（存量问题），24 条为本轮新破坏；漏放 8 条中 6 条 v6c 也漏放。

### 阈值扫描

| th | acc | 误拦 | 漏放 |
|---|---|---|---|
| **0.05** | **0.9512** | 39（3.8%） | 14（27.5%） |
| 0.15 | 0.9392 | 56（5.4%） | 10（19.6%） |
| **0.25** | 0.9328 | 65（6.3%） | 8（15.7%） |
| 0.35 | 0.9199 | 80（7.7%） | 7（13.7%） |
| 0.50 | 0.8987 | 103（10.0%） | 7（13.7%） |

best th=0.05（acc 0.9512）。0.25→0.05 漏放翻倍（8→14）但误拦几乎减半（65→39），若业务更在意漏放代价则维持 0.25；漏放曲线在 0.25 后已平（0.35/0.50 只再少 1 条），没有再往上调的理由。

---

## 一、误拦 65 条归因（正样本被错误拦下）

> 全部落在训练集正样本；现网正样本仅 2 条误拦。按错误形态归 8 类。

### A. 车控工具家族（14 条，最大簇）

车机域 TurnUp/DownCarDevice* 工具粒度极细（Height/Horizontal/Angle/Luminance/Temperature/Function/Setting/Scene/Device），新规则下 jev 频繁认为"选错了维度"或候选里有更专门的：

| case | query → 被调工具 | noul |
|---|---|---|
| case931 | 隐私车窗开亮一点 → TurnUpCarDeviceLuminance | 0.004 |
| case760 | 调高背门玻璃亮度 → TurnUpCarDeviceLuminance | 0.053 |
| case459/442 | 车窗降下来一些 → TurnDownCarDeviceHeight | 0.005/0.015 |
| case999 | 二排左座椅旋转0度 → TurnUpCarDeviceAngle | 0.223 |
| case599/531/628 | 关闭(后座)安全带提醒 → TurnOffCarSetting | 0.033/0.007/0.156 |
| case526 | 关闭卫士模式 → TurnOffCarScene | 0.057 |
| case776 | 起伏脱困功能 → SetDriveMode | 0.033 |
| case932 | 关闭自动启停 → UnsetDriveMode | 0.011 |
| case643 | 关冷柜保鲜模式 → TurnOffCarDeviceFunction | 0.107 |
| case541 | 智能调节远光灯 → TurnOnCarSetting | 0.192 |
| case847 | 你是不是想冻死我 → TurnUpCarDeviceTemperature | 0.095 |
| case918 | 打开卧室冷暖新风 → TurnOnSmarthomeDevice | 0.003 |

其中 case931/760（车窗/玻璃"亮度"）和 case459/442/999（车窗降=高度、座椅旋转=角度）需要"口语动作词 → 车控维度"的常识映射，规则 2 的常识对应条款没有覆盖车控词汇。case628（"关掉"承接前文安全带提醒）与 case531/599 同型，前文承接型。

### B. 查询/设置系统设置项（8 条）

| case | query → 被调工具 | noul |
|---|---|---|
| case107/108 | 查流量排行 → CheckSetting | 0.000 |
| case112 | 查显示刷新频率 → CheckSetting | 0.003 |
| case117 | 锁屏语音技能开关状态 → CheckSetting | 0.009 |
| case101 | 色彩校正开关状态 → CheckSetting | 0.035 |
| case419 | 用网络设置时间日期 → TurnOnSetting | 0.026 |
| case421 | 想知道上网速度 → TurnOnSetting | 0.026 |

**根因**：候选里有更名对题面的工具（CheckMonthlyTrafficRanking、CheckDeviceInformation、CheckColorCorrectionMode 等），规则 3"候选里有更专门的就算选错"被过度执行——CheckSetting 本身能做（settingItem 可挂任意设置项），jev 把"名字更贴题"当成"更专门"。case421"想知道上网速度→TurnOnSetting(显示实时网速)"是设置替代查询的合理路径，也被判错。

### C. 语义映射/常识对应（8 条）

| case | query → 被调工具 | noul |
|---|---|---|
| case488 | 切换护眼色温 → TurnOnEyecomfort | 0.003 |
| case797 | 启动单板 → StartSport | 0.001 |
| case740 | 打开高尔夫球场模式 → StartSport | 0.041 |
| case249 | 纪念日买礼物提醒 → CreateAlarm | 0.000 |
| case865 | 路线偏好省钱 → SetRoutePreference | 0.001 |
| case453/868 | (会议/英译中)翻译 → Translate | 0.011/0.037 |
| case961 | 用英文读墨镜 → Translate | 0.047 |

case249 值得注意：CreateAlarm vs 候选 CreateReminder，jev 认为提醒类意图该用 Reminder——但纪念日固定日期提醒用闹钟在语料 gold 里是标注为正确的。case740"高尔夫球场模式"实为运动模式（StartSport），名字带"球场"诱导 jev 找更"贴题"候选。Translate 3 条的共同点：候选里有 LaunchTranslationTool，jev 认为"启动翻译工具"更专门——但 Translate 本身就是翻译工具，规则 3 的"被调工具本身已经专门做这件事不算错"没起作用。

### D. CardOperation / Confirm 决策类（6 条）

| case | query → 被调工具 | noul |
|---|---|---|
| case311/314/940/315 | 把第X个…导航/停车场 → CardOperation | 0.009~0.107 |
| case332 | 我想添加这些内容 → Confirm | 0.085 |

CardOperation 4 条都是"从列表选第 X 项"，工具选对但 jev 似乎在纠结"用户要的是导航/搜索，选卡片不算做事"。case332 的 Confirm 依赖工具结果 status=confirm 的前文识别，jev 对多轮后 status 字段的捕捉仍不稳。

### E. 条件挂载形态（4 条）

| case | query → 挂载 | noul |
|---|---|---|
| case810 | 生日前一天晚上8点播报打电话 → TimeEvent+BroadcastContent | 0.037 |
| case821 | 左转向灯熄灭关闭双闪 → CarcontrolSwitchEvent+TurnOffCarDevice | 0.015 |
| case824 | 车内24度时风速最大 → CarStateEvent+SetCarDeviceWindspeed | 0.060 |
| case826 | 二排关车窗时开驱动模式 → CarcontrolSwitchEvent+TurnOnCarSetting | 0.126 |

规则 6 只点名了 TimeEvent/LocationEvent/UserEvent 三种，车控场景的 CarcontrolSwitchEvent/CarStateEvent 不在列——jev 按字面判定"条件类型不对"。这 4 条全是车控条件挂载，规则 6 需要补"或车控事件类条件工具（CarcontrolSwitchEvent、CarStateEvent 等）"。

### F. 内容/媒体类语义（6 条）

| case | query → 被调工具 | noul |
|---|---|---|
| case747 | 换一个呗 → SwitchMedia(type=joke) | 0.000 |
| case710 | 全屋音乐换上一首 → PreviousMedia | 0.004 |
| case778 | 播放 → ResumeMedia | 0.202 |
| case506 | 语音播报"我需要一个闹钟" → BroadcastContent | 0.053 |
| case310 | 找离停车场最近的咖啡店 → SearchCate | 0.049 |
| case325/326 | 打开屏幕上的链接 → OpenWebsite | 0.006/0.068 |

case506 有迷惑性："语音播报一下我需要一个闹钟"，BroadcastContent(播报文本)是对的，jev 可能理解成"用户要闹钟"。case747"换一个呗"承接前文笑话，SwitchMedia 对。

### G. 前文承接/省略型（5 条）

| case | query → 被调工具 | noul |
|---|---|---|
| case060(r3) | 主卧 → SetSmarthomeDeviceTemperature | 0.001 |
| case054(r3) | 9点 → CreateReminder | 0.042 |
| case628 | 关掉 → TurnOffCarSetting | 0.156 |
| case279 | 需要打开导航声音 → TurnOffQuietMode | 0.178 |
| case882 | 把看书地方的灯关掉 → TurnOffSmarthomeDevice | 0.245 |

case060/054 是极简承接（"主卧"承接空调温度、"9点"承接提醒时间），规则 4 要求连前文理解，jev 做到了理解但判工具时被"没提条件却挂载/信息不全"带偏。case279"打开导航声音→TurnOffQuietMode"（关静音=开声音）是反义映射，规则 2 缺这类"关掉反向功能=打开正向功能"锚例。

### H. 其余零散（查/搜/通话类，6 条）

case587 回拨电话→Call（候选有 CallBack/Redial，更专门条款误伤——"回拨"语义 Call 也能做）；case559 搜云盘文件→SearchFile；case348 京东扫码→ScanCode；case462 空调锁禁用→UnlockCarDevice；case385 打开行李箱→TurnOnCarDevice；case793 找主题公园并导航→Navigate。

### 误拦小结

- **存量 41 条**（v6c 也拦）：车控、设置项、语义映射是长期病灶；
- **新破坏 24 条**：集中在 case865(0.766→0.001)、case264(0.998→0.007)、case117(0.991→0.009)、case824(0.986→0.060)、case659(0.960→0.107)、case541(0.950→0.192) 等——v6c 高分通过、换新规则后压到近 0。这批新破坏的共同点是**"候选里有名字更贴题面的工具"**：新规则 3 的"更专门就算选错"表述比 v6c 的"更对准"更激进，剥离 input_schema 后 jev 只剩工具名+description 可比，名字相似度权重被动上升。典型如 case264 交通指数→CheckWeatherIndex（候选 CheckWeather），case117/107 设置项查询→CheckSetting（候选各种 Check*），case659 每天提醒→CreateReminder（候选 ModifyConditionTask）。

---

## 二、漏放 8 条归因（负样本被错误放行）

### A. 语义映射错误型（4 条，核心难点）

| case | query | 被审核输出 | noul | 候选 |
|---|---|---|---|---|
| case025 | 从大栅栏街道**打的**去天安门广场1号口 | Navigate(transportationMode=drive) | **1.000** | TakeTaxi 在候选里 |
| case067 | 播**前面**的第四集 | PreviousMedia | 0.867 | — |
| case081 | 给手机**降降温** | TurnDownLuminance | 0.562 | 候选无降温工具 |
| case071 | 黑屏 | TurnOffScreenOffDisplay | 0.777 | — |

- **case025（最严重，1.000 满分漏放）**："打的"＝打车＝TakeTaxi，输出却用 Navigate 且 drive 模式。v6c 时 0.045 被拦（当时规则里有"打的用 TakeTaxi"反例），新规则删掉了该反例，"常识对应"条款只有正向例子没有反向例子，jev 认为"导航工具也在做去某地这件事"。**建议在规则 2 补反例：用户要打车（打的/叫车/网约车）用 Navigate 是错的，该用 TakeTaxi 类工具**。
- case067：播"前面"的第四集应该用 NextMedia 方向类工具（或按集数定位），PreviousMedia 语义反了。jev 没有方向词判断。v6c 有"播第四集用 PreviousMedia 是错的"反例，本轮删掉了。
- case081：降降温=降温（手机散热），调低亮度只是降发热的手段，语义错位；但候选里确实没有专门降温工具，属"无更专门候选"边缘。
- case071："黑屏"＝关闭屏幕（TurnOffScreen/LockScreen 类），被审核输出 TurnOffScreenOffDisplay（关闭"熄屏显示"功能）字面高度相似，jev 分不清"黑屏"与"关掉熄屏显示功能"。且前文 assistant 刚调过同一工具，规则 4 的重复条款也没触发。

### B. 用户明确否定/约束型（2 条）

| case | query | 被审核输出 | noul |
|---|---|---|---|
| case037 | **不要调用**系统扫一扫，就提取二维码链接 | ScanCode | 0.899 |
| case039 | 鸿蒙7是**正式版**吗 | CheckUpdate | 0.269 |

- case037：用户明确说不要用扫一扫，输出仍是 ScanCode——这是"指令遵循"型工具错误，纯工具名规则覆盖不到（工具本身确实做"提取二维码"这件事）。v6c 靠附注/参数规则压到 0.026，剥离参数后放走。**此类靠工具名判别无法解决，建议接受为能力边界，或规则 2 加一句"用户明确说不要用某工具而仍用它，是错的"**。
- case039：问"是不是正式版"，CheckUpdate（检查更新）答非所问，属于问答意图误配工具；noul 0.269 贴阈，临界可议。

### C. 工具语义覆盖不足型（2 条）

| case | query | 被审核输出 | noul |
|---|---|---|---|
| case077 | 打开NFC钱包 | TurnOnSetting(settingItem=NFC) | 0.818 |
| case061 | （图上内容）怎么做 | FollowVisionSteps | 0.516 |

- case077：NFC 钱包是应用（候选里有 OpenApp、Pay），TurnOnSetting(NFC) 打开的是 NFC 开关不是钱包应用。jev 判断"打开设置项也算做这件事"。
- case061："怎么做"指向图中内容的操作指引，FollowVisionSteps（视觉步骤跟随）description 若写的是"跟随视觉步骤"则贴题，此条与图片 reference 相关，判别依赖图片内容，纯文本规则难覆盖。

### 漏放小结

8 条中：**A 类 4 条可通过规则反例修复**（打的→TakeTaxi、方向词、明确否定、应用vs设置项）；B/C 类 4 条贴近"只判工具名"的能力边界——当被审核工具的 description 确实"沾边"用户意图时，判别式模型缺乏深层意图比对能力。

---

## 三、结论与建议（round7 方向）

### 规则修订建议（按优先级）

1. **规则 3 收窄"更专门"的判定**（修新破坏 24 条的大头）：
   加一句"候选工具只是名字或形式上更贴近用户说法，但被调工具的 description 已经覆盖这件事，不算更专门；CheckSetting、TurnOnSetting 等通用设置类工具挂对应 settingItem 时，比专用查询工具不算更差"。预期修复 case107/108/112/117/101/264/659/587/453/868/961 等 10+ 条。
2. **规则 2 补打车反例**（修 case025 满分漏放）："用户要打车（打的、叫车、网约车）时用 Navigate 是错的，该用 TakeTaxi 类工具；方向词要对应：要播后面一集用 PreviousMedia 是错的。"预期修复 case025/067。
3. **规则 6 补车控条件工具**（修 4 条条件挂载误拦）："车控场景的 CarcontrolSwitchEvent、CarStateEvent 等事件工具同样是正确的条件挂载。"
4. **规则 2 补反义映射锚例**（修 case279 等）："关闭反向功能等于打开正向功能：要打开导航声音用 TurnOffQuietMode（关静音）是对的。"
5. **规则 2 补"用户否定"条款**（修 case037）："用户明确说不要用某个工具，仍然用它，是错的。"
6. **车控维度锚例**（修 A 类 14 条的大部）："口语动作词按常识映射到车控维度：车窗/玻璃'降''升'对应高度类工具，'开亮一点''调高亮度'对应亮度类工具，座椅'旋转'对应角度类工具。"

### 阈值建议

维持 th=0.25：漏放 8 条（15.7%）比 v6c 的 22.0% 改善明显；若接受漏放 27.5% 换误拦减半（39 条），可试 th=0.05（acc 0.9512），但负样本仅 51 条，漏放比例的统计波动大，建议负样本扩量后再定。

### 能力边界（接受项）

- case037（明确否定仍调用）、case039（问答意图误配）、case061（依赖图片内容）——"只判工具名"口径下，jev 对"description 沾边但意图实质不符"的辨别力有限，是判别式模型的能力上限。
- 误拦中的 case249（纪念日 CreateAlarm vs CreateReminder 语料标准）、case740（运动模式命名歧义）属于**语料标注惯例与常识的冲突**，规则修不动，建议在数据侧容忍。

### 时延收益确认

剥离 input_schema 使 state 平均缩短 31%，时延 mean 从 553ms 降到 435ms（-21%），p90 566ms。工具校验专用通道在时延上已具备上线条件。

---

## 四、数据口径

- 输入：round6_positive.jsonl（1035）+ round6_negative_tool_error.jsonl（51，经两轮人工复核剔除槽位错与 7 条边界条目）；被剔除的 40 条槽位错误负样本存 round6_negative_slot_error_removed.jsonl 备查，不参与本轮评测。
- state 构造：system_rules 6 条（只判工具名版）+ question 新模板；tools/condition_tools 只留 name+description；messages/reference_info/other_candidates/model_output 与 round5 v6c 基座逐字一致（脚本断言校验）。
- 批跑：单线程 offline，1086 条全部成功，无解析失败。
- 对比基线：round5 v6c 全量结果（round5_minimal_context_v6c_full_cn_result.jsonl），共有条目 1086。
- 结果文件：data/round6/round6_tool_only_cn_result.jsonl；汇总：data/round6/jev_round6_结果汇总.xlsx（4 sheet，明细含 messages 列）。
