# 自我 / astrbot_plugin_self

把三件本来分开的事合并成一个连续自我：

```text
人格演化     我说话多长、多冷、多近，以及我为什么变成这样
隐私记忆     谁在什么场合说了什么，能对谁重复、不能对谁重复
外部顾问     拿不准或被攻击时，先问一次，再用自己的口吻回答
```

它们共用一份状态（一个 SQLite），因此“对这个人更亲近”“这件事不能转述”“这次我请教过顾问”会互相影响，而不是各存各的。

## 和三个旧插件的关系

| 旧插件 | 现在的位置 |
|---|---|
| plastic_persona | `core/persona.py` |
| private_memory | `core/privacy.py` |
| assistant_bridge | `core/advisor.py` |

旧插件的数据不会自动迁移；本插件从空库开始，先跑一段时间再决定是否导入。

> **不要和旧的三件同时启用。** 三者都开着时，人格块会被注入两次、日记工具重名、
> 顾问会被调用两次，还会出现两套互不相认的记忆。启用本插件前，先在面板里把
> `astrbot_plugin_plastic_persona`、`astrbot_plugin_private_memory`、
> `astrbot_plugin_assistant_bridge` 停用。

## 存储与隐私

```text
self.db         SQLite，明文。profile / episodes / memories / people / advisor_log
diary.md        明文，仅私聊可读写
配置            plugin 配置 JSON，明文；api_key 也是明文
```

这些都是明文存在你自己的机器上，没有加密。同一台机器上的其它程序能直接读到。
如果你会共享这台机器，把 `data/plugin_data/astrbot_plugin_self/` 和
`data/private_self/` 的权限收一下。

发出去的只有两类：顾问调用时的提问（已做手机号/身份证/卡号/密钥替换），
以及你自己的消息（和平时聊天一样）。记忆与日记不会离开本机。

## 开发与运维工具

```text
tools/migrate.py     从旧三件导入叙事/倾向/经历（默认 dry-run，--apply 才写）
tools/verify_live.py 只读体检：10 项，不写库
tools/preview.py     本地预览面板（假数据 + 无头浏览器渲染检查）
tests/test_core.py   隐私矩阵 / 预算 / 人格 / 存储（81 项）
tests/test_page_api.py 面板接口 / 设置保存 / 迁移（36 项）
tests/test_tools.py  verify_live 的路径解析与 10 项体检（10 项）
tests/test_form.js   面板取值与展示辅助函数（Node）
```

## 决策顺序

```text
收到消息
  ├─ 记录：谁说的、多长、敏感度、能不能转述
  ▼
生成回复前
  ├─ 注入当前自我（叙事 / 倾向 / 与这个人的关系）
  ├─ 如果用户在打听第三个人 → 按敏感度决定能不能说
  └─ 如果拿不准或被攻击 → 问顾问，建议过滤后再注入
  ▼
生成回复后
  ├─ 微调表达倾向、学习口癖、记录重要经历
  └─ 每 N 条反思一次，重写自我叙事
```

## 配置要点

| 键 | 作用 |
|---|---|
| `learning_rate` | 表达倾向变化速度，默认 0.03 |
| `reflection_interval` | 每多少条回复反思一次 |
| `privacy_words` | 敏感词表，留空用内置 18 词 |
| `advisor_mode` | `current_provider` 或 `api` |
| `advisor_scope` | `both` / `private` / `group` |
| `advisor_per_hour` / `advisor_per_day` | 预算，防止刷爆 |
| `advisor_trigger_words` | 触发咨询的问题词，可覆盖内置 |

## 命令

```text
/人格状态     叙事、倾向、关系、顾问统计
/人格重置     清空叙事与统计（记忆和关系保留）
/助手 问题    直接问顾问
/助手状态     模式、范围、调用数、今日用量
```

## 模型工具

```text
private_diary_write(text, target=diary|self)   写日记 / 自我记录（仅私聊）
private_diary_read(target=diary|self)          读日记 / 自我记录（仅私聊）
self_narrative_append(text, reason)            在自我叙事后面追加一行（仅私聊 + 仅管理员）
```

`self_narrative_append` 只追加、不覆盖，单条上限 200 字，总长 2000 字；写入后会把
反思标记推到当前，避免下一轮反思把它冲掉。这是模型唯一能改自己叙事的入口，
需要管理员私聊；`/人格重置` 会连同版本号一起重置。

写到 `AstrBot/data/private_self/`。

## 数据

```text
AstrBot/data/plugin_data/astrbot_plugin_self/self.db
```

表：`profile` / `episodes` / `catchphrases` / `people` / `members` / `memories` / `advisor_log`。

两个容易漏的细节：`members` 是 `(user_id, group_id)`，私聊里能不能提群内容靠它；
`profile.narrative_version` 是叙事写入的乐观锁，反思和 `self_narrative_append` 都靠它防覆盖。

## 隐私语义

```text
场景等级   private(0) < group(1)
铁律一     内容不得流向更公开的场景（私聊 → 群聊 一律禁止）
铁律二     群内容不出本群；group_id 为空视为未知，一律拒绝
           本人跨群复述也拒绝——"这个人在别的群说过话"本身就是信息
铁律三     群里的公开低敏内容，可以在私聊里被提及
敏感度     high / mention / medium / low
可转述     只有 low；同群内允许，或从群到私聊允许
日记       仅私聊可读写；diary_admin_only=true 时仅管理员私聊
对外脱敏   发给顾问前先替换手机号、身份证、卡号、密钥
```

## 面板

插件拓展页里叫「自我」，包含：

```text
状态卡      存在天数、样本、经历、记忆、认识人数、顾问调用
自我叙事    当前叙事 + 重置按钮
倾向        话多 / 温度 / 表情 / 主动 四条进度条
成员表      昵称、发言数、亲近度、最后活跃；点一行看人物画像
人物画像    记忆（私聊/群分开）、所在群、管理员备注
顾问        模式、失败数、平均延迟；一行测试问题 + 最近 20 条记录
```

面板只读为主，写操作有三个：「重置叙事」「顾问设置 → 保存并生效」「人物画像 → 保存备注」。
两者都有二次确认或明确的状态提示，且不会读回 API Key。

## 迁移旧数据

```text
python tools\migrate.py            # 预览，不写入
python tools\migrate.py --apply    # 写入 self.db
```

从 `astrbot_plugin_plastic_persona/profiles.json` 读叙事、倾向、经历，
从 `astrbot_plugin_private_memory/private_memory.db` 读历史记忆。

导入的群记忆 `group_id` 留空，按“未知来源”处理——不会被转述，这是刻意保守。

## 测试

不依赖 AstrBot，纯离线，两份测试分开跑：

```text
python tests\test_core.py        81 项   隐私 / 预算 / 人格 / 存储 / 跨群
python tests\test_page_api.py    36 项   面板接口 / 设置保存 / 触发策略 / 迁移 / 私聊可见性
python tests\test_tools.py       10 项   verify_live 找库与体检项
node tests\test_form.js           1 项   面板取值（空值不回填成 0）
```

合计 128 项。改完代码先跑这几条，CI 也会跑同一组。

## 已知限制

- 顾问没有持久会话历史（每次独立提问）
- `observe_reply` 拿到的是**装饰前**文本（还没加 @、引用、分段）
- `capture` 用 `event_message_type(ALL)`，会把事件标记为 wake；多插件联动待验证
- 口癖只收纯汉字 2–4 字、且要复现两次以上才进提示词；仍可能学到语法通顺但没意义的碎片
- 记忆按「被 @ 或被唤醒」写入（capture_mode=addressed 时更窄），群里纯闲聊不进库
- 未实现向量检索，顾问只看当前问题与人格状态
- privacy_words 只替换内置的 11 个 high 词；另有 9 个 mention 词不可配置
- 卸载插件时不会注销 `register_web_api` 注册的路由；禁用后重启前接口仍可访问
- 面板的「测试连接」单独计额度（每小时 20 次，不占聊天配额），失败会退还
- 迁移默认不导入旧记忆：旧记忆没有群号，导入后既不能转述也查不到

## 路线

```text
0.3  顾问可调：面板 18 项设置 + 六种触发策略        ✅ 已完成
1.0  收尾：并发标记、capture_mode、叙事工具         ✅ 已完成
1.1  前端：亮色主题、局部失败降级、日志筛选         ✅ 已完成
1.2  关系维度可视化；路由注销、顾问采纳率统计
```
