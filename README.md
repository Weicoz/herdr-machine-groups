# Herdr Machine Groups

> 🏷️ Tag, group, and fold your Herdr SSH machines with an interactive TUI popup. Focus the Herdr sidebar on specific clusters with a single key.

---

## Why This Exists / 为什么需要这个插件

Herdr 的原生侧栏将所有已保存的远程机器平铺在 `▾ Machines` 列表中。当机器数量超过 5 台（云服务器、局域网主机、Mesh 虚拟网节点、测试机）时：
1. **侧栏臃肿**：大量机器占满侧栏可视区域，难以快速定位。
2. **缺乏分组与折叠**：原生数据结构没有 tag 属性，侧栏也不支持多级折叠目录。
3. **频繁断连成本高**：如果手动频繁 disable/enable 机器，每次恢复都会触发 SSH 重新握手。

**`herdr-machine-groups`** 为 Herdr 提供了轻量、无外部依赖的群组管理方案：
- 居中弹窗 TUI，支持键盘上下浏览、按组收起与展开。
- 支持按通配符模式（`patterns`）或标签（`tag`）自动将机器归类。
- 支持“群组专注”模式：一键让 Herdr 原生侧栏仅显示选中组的机器。
- **纯 Python 3 标准库（内置 curses）**，免装 `pip`，免依赖 `fzf` 或 `gum`。

```text
 ◈ Herdr Machine Groups & Clusters ◈                           共 9 台机器
──────────────────────────────────────────────────────────────────────────
 ▼ [云端服务器] #cloud (4/4 活跃)
    ● 腾讯云-134               (tx-134              ) [已启用]
    ● 腾讯云-42                (tx-42               ) [已启用]
    ● 腾讯云-43                (herdr-server-43     ) [已启用]
    ● 腾讯云-43-EasyTier       (herdr-server-43-eas…) [已启用]
 ▶ [办公与本地] #office (3/3 活跃) [已折叠]
 ▶ [EasyTier 虚拟网] #easytier (2/2 活跃) [已折叠]
──────────────────────────────────────────────────────────────────────────
 [↑/↓]移动  [Space]折叠/展开  [f]仅看此组  [a]显示全部  [t]开关侧栏  [q]退出
```

---

## Installation / 安装

### 本地开发 / 快速测试
```bash
herdr plugin link /absolute/path/to/herdr-machine-groups --enabled
```

### GitHub 安装（发布后）
```bash
herdr plugin install owner/herdr-machine-groups
```

---

## Keybindings / 键位配置

在 `~/.config/herdr/config.toml` 中添加快捷键绑定（推荐绑定到 `prefix+m`）：

```toml
[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "herdr-machine-groups.open"
description = "machines: groups & fold"

# 可选：直接通过快捷键聚焦常用组
[[keys.command]]
key = "prefix+shift+1"
type = "plugin_action"
command = "herdr-machine-groups.focus-cloud"
description = "machines: focus cloud"

[[keys.command]]
key = "prefix+shift+a"
type = "plugin_action"
command = "herdr-machine-groups.show-all"
description = "machines: show all"
```

配置后重载生效：
```bash
herdr server reload-config
```

---

## TUI Shortcuts / 弹窗快捷键

| 按键 | 说明 |
|---|---|
| `↑` / `k`, `↓` / `j` | 上下移动光标 |
| `Space` / `Enter` | 在分组行：**折叠 / 展开**该分组（记忆状态）<br>在机器行：切换该机器在侧栏的启用/隐藏 |
| `f` (Focus) | **仅看此组**：将当前组内机器在侧栏显示，其余机器全部隐藏 |
| `a` (All) | **全部显示**：恢复所有机器在侧栏的显示 |
| `t` (Toggle) | 批量切换当前分组内所有机器的启用/隐藏 |
| `r` (Refresh) | 重新读取 Herdr 当前机器列表 |
| `q` / `Esc` | 退出弹窗 |

---

## Configuration / 分组配置

首次启动会自动在 `~/.config/herdr/machine-groups.json` 生成默认配置，可随时按需编辑：

```json
{
  "groups": [
    {
      "id": "cloud",
      "name": "云端服务器",
      "tag": "cloud",
      "patterns": ["*腾讯云*", "tx-*", "*server*"],
      "collapsed": false
    },
    {
      "id": "office",
      "name": "办公与本地",
      "tag": "office",
      "patterns": ["*Mac-Mini*", "*ZERO-X*局域网*"],
      "collapsed": false
    },
    {
      "id": "mesh",
      "name": "EasyTier 虚拟网",
      "tag": "easytier",
      "patterns": ["*EasyTier*"],
      "collapsed": false
    }
  ]
}
```

- `patterns`：支持 Shell 通配符（如 `*`），同时匹配机器的 `label` 和 SSH `target`。
- 未匹配到任何模式的机器会自动进入 `未分组 (默认)`，不会遗漏。

---

## CLI Usage / 命令行调用

支持在脚本或其他工作流中直接调用：

```bash
# 查看所有分组及机器（JSON 输出）
python3 bin/machine-groups.py list

# 侧栏一键聚焦指定标签的分组
python3 bin/machine-groups.py focus cloud

# 侧栏恢复全部机器
python3 bin/machine-groups.py show-all
```

---

## License

MIT License.
