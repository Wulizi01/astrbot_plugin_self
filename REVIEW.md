# 自我插件 v1.1.0 — 评审说明

## 一句话

代码、测试、文档、打包、安装验证都已就位。**剩下的只有人工动作**：
点一次面板、发三条消息、填一个仓库地址。清单在 `发布检查单.md`。

## 1.0.x 相对 0.3.4 的改动

| 变更 | 为什么 |
|---|---|
| `consult()` 返回 `(answer, row_id)`；`mark_injected(row_id)` | 原来用 `MAX(id)` 标记，并发会标错行 |
| `log_advisor()` 返回行 id | 同上 |
| `capture_mode`：`all` / `addressed` / `off` | 给 is_wake 留一个降写入的杠杆；**钩子仍会被调用，wake 标记不会因此消失**，文档已写明 |
| `max_episodes` 300 → 2000 | 原上限是拍的数，没有依据 |
| 版本 1.0.0，author/repo 调整 | 发布准备 |

## 测试

```text
tests/test_core.py        66
tests/test_page_api.py    31
tests/test_form.js         1  （Node，5 条断言）
合计 98，全过
```

**安装验证**（10:56，从发布 zip 解压到临时目录）：

```text
顶层结构       astrbot_plugin_self\main.py   ✅ 没有多一层
pages 存在     pages\自我\index.html          ✅
py_compile     全部通过                       ✅
从解压副本跑测试   64 / 30 / Node 全过         ✅
包体积         0.3 MB
```

**真机**（10:53，版本 1.0.0）：

```text
插件加载      无报错
verify_live   10/10
面板测试连接  success=true，1391 ms   ← 走通了 consult 的新返回结构
```

## 人工验证（11:12–11:16，已完成）

```text
面板渲染       六格数字 / 叙事 / 四条进度条 / 设置卡，均正常
保存生效       11:12 保存 hostile_only 后，同一进程 GET 立即返回新值（未重载）
热生效对照     11:14:30 hostile_only 下发「为什么会这样，你能分析下吗?」→ 顾问无记录
              11:15:14 keywords 下同一句 → id=6，1827 ms，injected=1
测试连接       10:53:33 / 10:57:16 两次，source=page，1296 / 1358 ms
重置叙事       叙事清空，记忆 32 条、经历 58 条保留
攻击路由       11:00:31「你这bot真垃圾」→ route，5062 ms，injected=1
叙事自写       self_narrative_append 调用两次，89 → 217 字，原句未改
```

## 仍未覆盖

```text
多路并发下的 mark_injected          已按行 id，但没有并发用例
捕获钩子的 is_wake 影响              只能压测，无法单测
群→私聊 放宽后没有做群内实测        只有 4 条单元测试
```

## 已知限制（1.0 接受）

```text
capture 的 ALL 监听仍会置 is_wake（capture_mode 只减写入，不取消钩子）
卸载插件时 register_web_api 路由不注销
顾问「测试连接」不计预算
迁移默认不导旧记忆（group_id 为空，导了也查不到）
口癖仍可能学到碎片
repo 字段为空，发布前需填
```

## 数据快照（10:54，`verify_live.py`）

```text
叙事   89 字（凌晨反思跑过一次）
样本   26    经历 57    记忆 29    成员 2    顾问日志 2
```

## 回滚

```text
面板禁用 self，启用 plastic_persona / private_memory / assistant_bridge，
删 data\plugins\astrbot_plugin_self，重启。
旧插件的数据从未被写入。
```
