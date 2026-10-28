# 修复记录

## v1.1.6 — 打包有自己的工具了

| 问题 | 修法 | 用例 |
|---|---|---|
| 打包一直是临时脚本在 `%TEMP%` 里现写现用：曾出现多一层目录、PowerShell 写出反斜杠条目、`data/cmd_config.json` 差点进包 | `tools/package.py`：白名单收集 → 单层 `astrbot_plugin_self/` + `as_posix()` 路径 → `verify()` 结构自检（单顶层、无反斜杠、无 pycache/db、非 ASCII 名带 UTF-8 标志）→ `--check` 解压后 `compileall` | `PackageTests`（5 项，含"凭据永不出现在包里"） |
| 版本号靠手写在 metadata 与 main.py 两处 | 打包时从 `metadata.yaml` 读版本，文件名自带；`verify` 之外不碰源码 | `test_build_is_single_layer_with_posix_names` |

## v1.1.5 — 卸载时摘掉面板路由

| 问题 | 修法 | 用例 |
|---|---|---|
| 插件被禁用/重载后，`register_web_api` 注册的 9 条路由还留在 `context.registered_web_apis` 里，接口在重启前一直可访问 | `Star.terminate()` 里调用 `page_api.drop_routes()`：按 `/astrbot_plugin_self/page` 前缀原地剔除（dashboard 持有同一个 list 引用）；AstrBot 没有 `unregister_web_api`，这是官方生命周期里唯一稳定的入口 | `RouteTeardownTests`（4 项：只删自己的、兼容对象形态、原地改、幂等与缺属性） |

## v1.1.4 — 面板测试也计数

| 问题 | 修法 | 用例 |
|---|---|---|
| 「测试连接」是真实模型调用，却不计预算，等于一个免费的模型代理 | 单开 `panel:test` 额度桶，每小时 20 次，冷却不适用；调用失败退还额度 | `test_panel_bucket_is_separate_from_chat`、`test_panel_has_no_cooldown`、`test_panel_refund_returns_the_slot`、`test_panel_default_cap` |
| 面板端点没有用例 | 用假的 `quart.request` 覆盖三条路径：优先 `consult_panel`、没有时退回 `consult`、额度用完时返回错误而不是抛异常 | `AdvisorTestEndpointTests`（3 项） |
| README 两个「工具」标题重名、数据一节漏 `members` 与 `narrative_version` | 改名为「开发与运维工具 / 模型工具」，补两张表与乐观锁说明 | — |
| CI 只在 ubuntu 上跑 | 加 windows-latest，覆盖 `verify_live` 的路径解析 | `.github/workflows/ci.yml` |

## v1.1.3 — 人物画像卡

| 改了什么 | 细节 |
|---|---|
| 面板新增人物画像 | 点成员表任意一行，右侧展开：QQ、发言数、亲近度、记忆条数（私聊/群分开）、首次与最近活跃、所在群 |
| 备注（管理员手写） | 每人最多 500 字，存在 `people.notes`；写进 `internal_self_model` 的「你对这个人的备注」一行，下一轮生效 |
| 新接口 | `GET /person?user_id=` → 画像；`POST /person/notes` → 保存备注 |
| 只读边界不变 | 备注只能由管理员在面板写；模型只能通过提示词看到，没有写入口 |

## v1.1.2 — 口癖只收真口癖

| 问题 | 修法 | 用例 |
|---|---|---|
| 口癖把 `jpg`、`2333`、`awsl`、`@某人`、纯符号都当成短语收进去，每轮提示词里挂着噪音 | 抽取时只收纯汉字 2–4 字（`_shape_ok`），原有虚词表与停用词不变 | `test_extract_catchphrases_drops_shape_noise`、`test_extract_catchphrases_keeps_short_chinese` |
| 只说过一次的句子碎片也会进提示词 | 提示词侧要求 `min_count=2`（说两遍才算习惯）；面板仍显示全部，方便排查 | `test_top_catchphrases_min_count_keeps_habits_only` |
| `verify_live` 碰到空库、半截库直接抛 traceback | 捕获 `sqlite3.Error`，输出一行「库结构」失败项；顺手把找库逻辑和 10 项体检写进用例 | `tests/test_tools.py`（10 项） |

## v1.1.1 — 重置的第二条入口

| 问题 | 修法 | 用例 |
|---|---|---|
| `/人格重置` 直接写 profile，绕过 `narrative_version`，进行中的反思会把旧叙事写回 | 命令改为调用 `store.reset_narrative()`，与面板同一入口 | `test_command_goes_through_reset_narrative`（静态断言禁止 `set_profile(narrative=...)`） |
| README 三处漂移 | 补 `self_narrative_append` 工具说明；删掉已移出仓库的检查单死链；更正记忆写入条件与敏感词数量 | — |
| `mark_injected` 只有「按行 id」的说法，没有用例 | 补 6 线程并发用例；把实现退回 `MAX(id)` 时该用例会红（已验证） | `test_concurrent_mark_injected_marks_its_own_row`、`test_mark_injected_ignores_zero_and_keeps_others_untouched` |

新增 GitHub Actions：push / PR 自动跑测试与 `compileall`。

## v1.1.0 — 前端：少踩坑、少让人猜

| 项 | 做法 |
|---|---|
| 亮色主题 | 颜色全提成 CSS 变量，补 [data-theme="light"] 一套；无 data-theme 时按 prefers-color-scheme 兜底；?theme=light|dark 只供本地截图 |
| 接口失败不再全黑 | Promise.allSettled，四个接口各自渲染，失败的那块挂一行红字，连接状态显示「部分失败 n/4」 |
| 表单不再被重建 | 表单只构建一次，之后只回填 alue；用户改过（dirty）就不覆盖，卡片头显示「未保存」；改成 <form>，回车即可保存 |
| 范围前置 | /advisor/settings 返回 
anges 与 	ypes，数字框带 min/max/step，字段下写「留空=不改，范围 a–b」 |
| 测试连接有秒表 | 每 0.5 秒更新已等秒数，并提示 60 秒超时；期间 ria-busy |
| 日志可筛 | 全部 / 失败 / route 三个 chip，时间改成「3 分钟前」，长回答折叠 |
| 成员表可排序 | 句数 / 亲近 / 最近，亲近度改成细进度条，最近活跃用相对时间 |
| 无障碍 | toast 
ole=status、ria-live，按钮 :focus-visible 轮廓，叙事过长可折叠 |
| 转义补引号 | escapeHtml 增加 " 与 '，避免以后被用作属性时出现 XSS |

测试：66 + 31 + Node 1 = **98**。前端离线渲染两种主题均通过（见 panel_light.png / panel_dark.png）。

# 修复记录

## v1.0.3 — 重置与反思的竞态 + 标签空白变体

| 缺口 | 修法 | 用例 |
|---|---|---|
| 
eset_narrative 不递增版本，反思可能把重置覆盖回去 | 重置也 +1 版本；_reflect 比对失败即丢弃 | 	est_reset_narrative_bumps_version |
| 标签正则漏 </internal_self_model >、<private_memory> | 放宽为 </?(?:internal|private)_[^>]*> | 	est_append_narrative_strips_loose_tag_variants |

测试：66 + 30 + Node 1 = **97**。

# 修复记录

## v1.0.2 — 叙事工具的绕过路径

评审实测出四条，全部处理：

| 绕过 | 修法 | 用例 |
|---|---|---|
| 任何私聊用户都能改叙事 | 工具加管理员闸门 | 工具层，未单测 |
| </internal_self_model> 标签逃逸，变成持久注入 | 写入前剥掉 </?internal_*>（大小写不敏感） | 	est_append_narrative_strips_prompt_tags |
| 只追加可当整体替换 | 单条上限 200 字 | 	est_append_narrative_rejects_oversized_entry |
| 反思竞态会覆盖刚写的行 | 
arrative_version +1，_reflect 写回前比对版本，不一致就丢弃叙事 | 	est_append_narrative_bumps_version |

另修 capture_mode=addressed：原来用 _to_bot（关键词）判断，@ 消息的正文里没有bot会被误丢；改为 event.is_at_or_wake_command，并在 schema 写明该模式会让成员表与「共同群」退化。

测试：64 + 30 + Node 1 = **95**。

# 修复记录

## v1.0.1 — 让 bot 能真的改写自己的叙事

它说「我只在旁边补一行」，但当时没有任何工具能写叙事——那句话落空了。

| 新增 | 说明 |
|---|---|
| `self_narrative_append` 工具 | 仅私聊；只追加不覆盖；上限 2000 字；写入后把 `last_reflection` 推到当前，防止被下一次反思冲掉 |
| `store.append_narrative()` | 追加逻辑 + 长度校验，4 条用例 |

真机：1.0.1 已加载，`/api/v1/tools` 里 `self_narrative_append active=True`。
测试：61 + 30 + Node 1 = **92**。


## v1.0.0 — 收尾版（历史）

| 变更 | 说明 |
|---|---|
| `consult()` 返回 `(answer, row_id)` | 调用方标记**那一行**，不再靠 `MAX(id)` |
| `mark_injected(row_id)` | 并发调用不会互相标错行 |
| `log_advisor()` 返回行 id | — |
| `capture_mode` | `all` / `addressed` / `off`，控制写库量 |
| `max_episodes` | 300 → 2000，配置项 |
| 版本号 | 1.0.0 |

真机（10:53）：插件 1.0.0 加载无报错；`verify_live` 10/10；面板「测试连接」成功（1391 ms），走通 `consult` 新返回结构。

测试：57 + 30 + Node 1 = **88**。

已知限制见 `发布检查单.md`。

## v0.3.3 — 前端把空值变成 0

评审发现的真 bug：`app.js` 用 `Number("") === 0` 把清空的字段写成了 0，后端的
"空字符串 = 保持原值" 从面板走不到——测试直接传 `""`，测的不是用户走的路。

| 问题 | 修法 | 用例 |
|---|---|---|
| 清空数字 → 0（per_hour 变不限、冷却归零、概率永不触发） | 抽出纯函数 `pages/自我/form.js::collect()`：空值与非法值直接跳过 | `tests/test_form.js`（Node，5 条断言） |

```text
node tests/test_form.js
```

测试合计：57 + 30 + 1 = **88**。

## v0.3.2 — 群 → 私聊真的接上

| 问题 | 修法 | 用例 |
|---|---|---|
| REVIEW 声称已放宽，实际私聊查询只取 `scope='private'` | `members` 表 + `find_memories_for_private()`（共同群校验） | `PrivateScopeTests` 4 条 |
| `addressed` 在面板没有选项，旧配置保存即被改 | GET 归一成 `explicit` | `test_settings_normalises_addressed` |
| 钳制静默，填 9 存 2.0 且表单不回显 | 保存后回填 + 提示 | `test_coerce_clamps_ranges` |
| `RANGES` 与代码下限不一致 | 收成 3/10 | 同上 |
| `saved=false` 静默回退 | `logger.warning` + 面板提示 | — |
| `verify_live` 把重置后的空叙事判失败 | 视为等待反思 | 工具（10/10） |

## v0.3.1 — 顾问设置写路径收尾

评审指出 0.3.0 的功能是对的，但写路径有四个具体缺陷、文档落后一版。

| 问题 | 修法 | 用例 |
|---|---|---|
| `page_api.py` 用了 `json.loads` 却没 `import json`，`_schema_defaults()` 每次 NameError 并被 `except: return {}` 吞掉 | 补 import；异常改为 `logger.warning` 不再静默 | `test_settings_fall_back_to_schema_defaults` |
| `addressed` 名不副实（on_llm_request 只在要回复时触发，"被点名"等于 always） | 改名 `explicit`，`addressed` 保留为同义旧名；面板与 schema 同步 | `test_explicit_policy`、`test_addressed_is_legacy_alias_of_explicit` |
| 保存路径无测试；空数字被前端变成 0 | 抽出 `_coerce_settings()`：空值跳过、范围钳制、非法值报错且不写入 | `test_coerce_*` 共 5 条 |
| 保存响应回传 api_key | 返回前剔除敏感键 | `test_coerce_keeps_key_only_when_provided` |
| 文档落后：54/10、写操作、路线图 | README 与 REVIEW 全部对齐 | — |

真机验证（01:58）：`POST /advisor/settings/save` 把 `advisor_trigger_policy` 写成 `hostile_only`，
`data/config/astrbot_plugin_self_config.json` 已落盘，响应 `{"applied":{"advisor_trigger_policy":"hostile_only"},"saved":true}`，不含 Key。

测试：57 + 25 = **82 项全过**。

## v0.3.0 — 顾问可调

| 新增 | 说明 |
|---|---|
| 面板设置卡 | 18 个字段：模式、API、模型、温度、超时、范围、预算、触发策略、提示词，保存即生效 |
| 触发策略枚举 | `keywords`（默认）/ `addressed` / `hostile_only` / `probabilistic` / `always` / `off` |
| 概率触发 | `advisor_trigger_probability`，只在 `probabilistic` 下生效；显式请求与攻击不受概率影响 |
| 设置接口 | `GET /advisor/settings`、`POST /advisor/settings/save`，API Key 只回传空值，留空表示不改 |

测试：57 + 18 = **75 项全过**（新增 6 条策略表、2 条设置接口）。

## v0.2.2 — 真机测试后的两处调整

| 变更 | 原因 | 用例 |
|---|---|---|
| 群→私聊放宽：群里的 low 公开内容可在私聊提及 | 真机发现"私聊问群里聊了啥"也被拒，过严 | `test_disclosure_allows_group_content_in_private`、`test_disclosure_blocks_sensitive_group_content_in_private`、`test_disclosure_blocks_private_content_in_group_still` |
| 顾问日志 `injected` 永远为 0 | 标记函数按 session 匹配，但表里没有 session 字段 | 真机确认（缺自动化用例，已记入未覆盖） |

测试：`test_core.py` 57 项 + `test_page_api.py` 10 项 = **67 项全过**。

### 真机结果（2026-10-28 01:20–01:24）

```text
日记写入        private_diary_write 成功，diary.md 1.5 KB
攻击路由        顾问 2375 ms，注入 178 字，回复克制
is_wake 副作用  "今天好冷" 被门禁拦下，未误回
跨群隔离        群 652491715 的记录在群 1132039297 被拒
插件冲突        5 个旧插件禁用，日志无残留
```

## v0.2.1 — 真机前的硬阻塞修复

评审在 `--apply` 时崩了：`python tools\migrate.py` 的 `sys.path[0]` 是 `tools\`，
`from core.store import` 找不到。预览能过、只有写入才炸，正好在信任之后。

| 问题 | 修法 | 覆盖用例（文件::用例） |
|---|---|---|
| 迁移 `--apply` 崩溃 | `sys.path.insert(0, str(ROOT))` | `test_page_api.py::MigrateTests::test_apply_imports_narrative_and_sets_reflection_marker` |
| 导入后第一条回复立刻覆盖叙事 | `apply()` 写入 `last_reflection = samples` | 同上断言 `last_reflection == 147` |
| `born_at` 没导入，面板永远显示 1 天 | 读取旧 `created_at` 写入 `born_at` | 同上断言 `born_at == 1793040238.0` |
| 迁移不幂等 | 经历按 `role+text` 去重，再加 `--apply` 不会翻倍 | `test_apply_is_idempotent_for_episodes` |
| 71 条旧记忆导入后不可用 | 默认**不导**；`--with-memories` 时才导，且标 `scope=legacy`、`shareable=0` | `test_memories_are_skipped_by_default`、`test_memories_are_marked_legacy_when_requested` |
| 原始时间戳丢失 | `add_episode/add_memory` 支持 `at` 参数 | 迁移用例断言经历条数 |
| 面板人数上限 200 | 新增 `store.count_people()`，面板用 COUNT | `test_page_api.py::PageApiTests::test_people_count_is_not_capped` |
| README 自相矛盾（“没有面板”） | 删除该条，补三条新限制 | — |

测试：`test_core.py` 54 项 + `test_page_api.py` 10 项 = **64 项全过**。

### 未覆盖（明确列出）

```text
面板页面的真实渲染与点击（用 tools/preview.py 做过离线 headless 校验，非 AstrBot 环境）
AstrBot 插件页桥接与鉴权
插件卸载时路由不注销（已知限制）
「测试连接」不计预算（已知限制）
```

## v0.2.0 — 功能补完（供审前）

不是修 bug，是把缺的内容补上，让插件像个成品。

| 新增 | 说明 |
|---|---|
| 面板 | `pages/自我/`：状态卡、叙事、倾向条、成员表、顾问日志、测试连接、重置叙事 |
| 面板 API | `page_api.py`：`/overview` `/people` `/advisor/log` `/advisor/test` `/reset` |
| 迁移脚本 | `tools/migrate.py`：从 plastic_persona 与 private_memory 导入，默认 dry-run |
| 口癖过滤 | 停用词表 + 排除“的/了/吗”类碎片，不再学“真的/好的” |
| episodes 上限 | 每次写入后裁剪到最近 300 条，避免无限增长 |
| 成员表 | `store.list_people()`，供面板展示 |

测试 **54 项**（+4：成员排序、顾问记录顺序、重置保留记忆、episodes 裁剪）。

### 仍未做

```text
capture 的 ALL 监听置 is_wake —— 需真机联调
超时写失败日志 —— 只有代码路径，无自动化用例
repo 占位符、发布元数据
```

## v0.1.2 — 第二轮评审后的修复

上一轮有一项是**假修复**（group_id 只写不读），本轮补齐，并新增 7 条用例。测试 **50 项全过**。

| 评审问题 | 修法 | 锁住它的用例 |
|---|---|---|
| 跨群仍可转述（group_id 只写不读） | `_allowed` 增加群比较：群内容只在本群内、`group_id=''` 视为未知一律拒绝、本人跨群也拒绝 | `test_disclosure_blocks_cross_group`、`test_disclosure_allows_same_group`、`test_disclosure_blocks_own_cross_group`、`test_disclosure_blocks_unknown_group` |
| `find_memories` 查询不带群 | 增加 `group_id`、`scope` 过滤参数，主流程按当前群查 | `test_disclosure_allows_same_group` |
| 退款把限流一起退了 | `refund(key, keep_cooldown=True)` 只退配额，把最近一次尝试时间推到当前，形成失败退避 | `test_refund_keeps_cooldown_for_backoff` |
| 人名提取不稳 | 先用 `people.name` 做最长匹配，正则只做兜底 | `test_match_known_person_prefers_longest`、`test_match_known_person_falls_back_to_regex` |
| 超时不算失败 | `consult` 单独捕获 `CancelledError` 并写 `ok=0` 记录 | 需运行时验证（离线无法制造取消） |
| 日记只限私聊、不限人 | 增加 `diary_admin_only`（默认 false，保持“仅私聊”），开启后非管理员私聊也拒绝 | 需运行时验证 |

### 仍然未做

```text
capture 的 ALL 监听会置 is_wake —— 需真机联调
口癖碎片、episodes 无上限、repo 占位符
「超时写失败日志」目前只有代码路径，没有自动化用例
```

## v0.1.1 — 第一轮评审后的修复

第一轮 35 项测试 → 43 项。详见下表。

针对外部评审，逐条修复并补测试。测试从 35 项增加到 **43 项**，全部通过。

## P0

| 评审问题 | 修法 | 测试 |
|---|---|---|
| 日记工具无闸门，群里可诱导读取 | `private_diary_write/read` 增加 `is_private_chat()` 判断，群聊直接拒绝 | 需运行时验证 |
| `own` 只看 speaker，私聊内容可在群复述 | 引入场景等级：private=0，group=1；**当前场景比来源更公开就拒绝**，与是否本人无关 | `test_disclosure_blocks_own_private_content_in_group` |
| memories 无 group_id，群 A 的话可被群 B 问 | 表增加 `group_id` 列（含旧库 ALTER 迁移），写入时记录 | `test_memory_roundtrip` |
| 人名正则贪婪，提取失败或带谓语 | 改非贪婪 + 前置边界，剥离“问/关于/和/跟”等谓语 | `test_extract_person_strips_leading_verb` |

## P1

| 评审问题 | 修法 | 测试 |
|---|---|---|
| `redact` 用 `\b`，中文场景失效 | 去掉 `\b`，改用 `(?<!\d)…(?!\d)` 上下文断言；补身份证/卡号 | `test_redact_hides_secrets_without_spaces` |
| 敏感词表一刀切，“喜欢”判 high | 拆成 `high`（真秘密）与 `mention`（普通提及）；**只有 low 可转述**，medium/mention/high 一律锁死 | `test_mention_words_are_not_secret`、`test_long_text_is_not_shareable` |
| 无 terminate，任务不回收 | 增加 `terminate()`；反思任务存入集合，`add_done_callback` 清理，卸载时 cancel + await | 需运行时验证 |
| 失败也占额度 | 新增 `Budget.refund()`，路由失败时退还 | `test_refund_returns_quota` |
| route 超时与 advisor 超时冲突 | 取 `min(route_timeout, advisor_timeout)` | — |
| `temperature=0` 被 `or` 吃掉 | 改为显式 `None` 判断 | — |
| 空闲会话键只增不减 | `allow()` 内增加 `_prune()` | — |

## P2

| 评审问题 | 修法 |
|---|---|
| 无 WAL | 每次连接设置 `journal_mode=WAL` + `busy_timeout=5000` |
| 旧 zip 与新代码不一致 | 交付只保留一个带版本号的压缩包 |
| 缺 LICENSE | 新增 MIT |

## 尚未处理（保留在待办）

```text
1. capture 使用 event_message_type(ALL) 会置 is_wake，
   可能影响 group_reply_gate / private_companion / proactive_chat 的联动，
   需要真实环境联调后再决定是否换实现
2. 口癖仍按标点切 2–4 字，会学到“真的/好的”这类碎片
3. 记忆只在 _to_bot 命中时写入，与 README“谁在什么场合说了什么”不完全一致
4. repo 地址仍是占位符
```

## 文档修正

评审指出钩子顺序写反了：`inject_self(40)` 实际先于 `route_advisor(30)`。
README 已按真实执行顺序改写，并注明 `observe_reply` 拿到的是**装饰前**文本。
