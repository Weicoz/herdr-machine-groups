#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
herdr-machine-groups: Group, tag, and fold Herdr SSH machines with interactive TUI and sidebar sync.
"""

import curses
import fnmatch
import json
import os
import re
import subprocess
import sys
import unicodedata

HERDR_BIN = os.environ.get("HERDR_BIN_PATH", "herdr")
PLUGIN_ROOT = os.environ.get("HERDR_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.environ.get("HERDR_PLUGIN_CONFIG_DIR", os.path.expanduser("~/.config/herdr/plugins/config/herdr-machine-groups"))
GLOBAL_CONFIG = os.path.expanduser("~/.config/herdr/machine-groups.json")
LOCAL_CONFIG = os.path.join(CONFIG_DIR, "groups.json")

def get_config_path():
    if os.path.exists(GLOBAL_CONFIG):
        return GLOBAL_CONFIG
    if os.path.exists(LOCAL_CONFIG):
        return LOCAL_CONFIG
    return GLOBAL_CONFIG

def str_width(s):
    """Calculate terminal display width accounting for wide CJK characters."""
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return w

def pad_str(s, target_width):
    current = str_width(s)
    if current < target_width:
        return s + " " * (target_width - current)
    return s

def clean_label(label):
    """Strip existing [Prefix] from label to get raw name."""
    return re.sub(r"^\[.*?\]\s*", "", label).strip()

def run_herdr(args):
    cmd = [HERDR_BIN] + args
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return res.stdout.strip()
    except Exception as e:
        return None

def fetch_machines():
    out = run_herdr(["machine", "list", "--json"])
    if not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, list):
            return data
        return data.get("machines", [])
    except Exception:
        return []

def get_default_config():
    return {
        "sync_sidebar": True,
        "sidebar_prefix": True,
        "groups": [
            {
                "id": "cloud",
                "name": "云端",
                "tag": "cloud",
                "patterns": ["*腾讯云*", "tx-*", "*aliyun*", "*aws*", "*server*"],
                "collapsed": False
            },
            {
                "id": "office",
                "name": "办公",
                "tag": "office",
                "patterns": ["*Mac-Mini*", "*ZERO-X*局域网*", "*local*", "*lan*"],
                "collapsed": False
            },
            {
                "id": "mesh",
                "name": "EasyTier",
                "tag": "easytier",
                "patterns": ["*EasyTier*"],
                "collapsed": False
            }
        ]
    }

def load_config():
    path = get_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), path
        except Exception:
            pass
    cfg = get_default_config()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cfg, path

def save_config(cfg, path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass

def group_machines(machines, config):
    groups = []
    used_ids = set()

    for g_def in config.get("groups", []):
        patterns = g_def.get("patterns", [])
        matched = []
        for m in machines:
            m_id = m.get("id")
            raw_label = clean_label(m.get("label", ""))
            target = m.get("target", "")
            if m_id in used_ids:
                continue
            is_match = False
            for p in patterns:
                if fnmatch.fnmatch(raw_label, p) or fnmatch.fnmatch(target, p) or fnmatch.fnmatch(m.get("label", ""), p):
                    is_match = True
                    break
            if is_match:
                matched.append(m)
                used_ids.add(m_id)
        groups.append({
            "def": g_def,
            "machines": matched
        })

    # Ungrouped leftovers
    ungrouped = [m for m in machines if m.get("id") not in used_ids]
    if ungrouped:
        groups.append({
            "def": {
                "id": "ungrouped",
                "name": "未分组",
                "tag": "other",
                "collapsed": False
            },
            "machines": ungrouped
        })

    return groups

def sync_sidebar(config, machines=None):
    """Synchronize folded states to the native Herdr sidebar without touching machine labels."""
    if machines is None:
        machines = fetch_machines()
    groups = group_machines(machines, config)
    toggled_count = 0

    for g in groups:
        g_def = g["def"]
        collapsed = g_def.get("collapsed", False)

        for m in g["machines"]:
            m_id = m.get("id")
            cur_enabled = m.get("enabled", True)
            target_enabled = not collapsed
            if cur_enabled != target_enabled:
                action = "enable" if target_enabled else "disable"
                run_herdr(["machine", action, m_id])
                toggled_count += 1

    return toggled_count

def reset_all_labels(machines=None):
    """Remove all [Prefix] labels from machines."""
    if machines is None:
        machines = fetch_machines()
    count = 0
    for m in machines:
        cur_label = m.get("label", "")
        base_label = clean_label(cur_label)
        if cur_label != base_label:
            run_herdr(["machine", "rename", m["id"], "--label", base_label])
            count += 1
    return count

class TUI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.config, self.config_path = load_config()
        self.machines = fetch_machines()
        self.cursor = 0
        self.status_msg = ""
        self.collapsed_map = {g.get("id"): g.get("collapsed", False) for g in self.config.get("groups", [])}
        # Initial sync on open if enabled
        if self.config.get("sync_sidebar", True):
            sync_sidebar(self.config, self.machines)
            self.machines = fetch_machines()

    def reload(self):
        self.machines = fetch_machines()

    def build_items(self):
        groups = group_machines(self.machines, self.config)
        items = []
        for g in groups:
            g_def = g["def"]
            g_id = g_def.get("id")
            is_collapsed = self.collapsed_map.get(g_id, g_def.get("collapsed", False))
            items.append({
                "type": "group",
                "id": g_id,
                "def": g_def,
                "machines": g["machines"],
                "collapsed": is_collapsed
            })
            if not is_collapsed:
                for m in g["machines"]:
                    items.append({
                        "type": "machine",
                        "group_id": g_id,
                        "data": m
                    })
        return items

    def set_machine_enabled(self, profile_id, enable):
        action = "enable" if enable else "disable"
        run_herdr(["machine", action, profile_id])

    def toggle_group_fold(self, g_id):
        new_val = not self.collapsed_map.get(g_id, False)
        self.collapsed_map[g_id] = new_val

        # persist to config
        for g in self.config.get("groups", []):
            if g.get("id") == g_id:
                g["collapsed"] = new_val
        save_config(self.config, self.config_path)

        # Sync fold to sidebar: if collapsed, disable group machines; if expanded, enable them
        if self.config.get("sync_sidebar", True):
            groups = group_machines(self.machines, self.config)
            for g in groups:
                if g["def"].get("id") == g_id:
                    for m in g["machines"]:
                        self.set_machine_enabled(m["id"], not new_val)
                    break
            self.reload()
            state_str = "折叠 (侧栏隐藏)" if new_val else "展开 (侧栏显示)"
            self.status_msg = f"✓ 分组已{state_str}"
        else:
            state_str = "折叠" if new_val else "展开"
            self.status_msg = f"✓ 分组已{state_str}"

    def focus_group(self, target_group_id):
        target_machines = []
        other_machines = []
        target_name = ""

        groups = group_machines(self.machines, self.config)
        for g in groups:
            if g["def"].get("id") == target_group_id:
                target_name = g["def"].get("name")
                target_machines.extend(g["machines"])
            else:
                other_machines.extend(g["machines"])

        for m in target_machines:
            self.set_machine_enabled(m["id"], True)
        for m in other_machines:
            self.set_machine_enabled(m["id"], False)

        # Update collapsed map: target uncollapsed, others collapsed
        for g in self.config.get("groups", []):
            g_id = g.get("id")
            if g_id == target_group_id:
                g["collapsed"] = False
                self.collapsed_map[g_id] = False
            else:
                g["collapsed"] = True
                self.collapsed_map[g_id] = True
        save_config(self.config, self.config_path)

        self.reload()
        self.status_msg = f"✓ 侧栏已聚焦 [{target_name}]：显示 {len(target_machines)} 台，其余已折叠"

    def show_all(self):
        for m in self.machines:
            self.set_machine_enabled(m["id"], True)
        for g in self.config.get("groups", []):
            g["collapsed"] = False
            self.collapsed_map[g.get("id")] = False
        save_config(self.config, self.config_path)
        self.reload()
        self.status_msg = f"✓ 侧栏已全部展开并显示 {len(self.machines)} 台机器"

    def run(self):
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)
        curses.use_default_colors()

        curses.init_pair(1, curses.COLOR_CYAN, -1)     # Group header
        curses.init_pair(2, curses.COLOR_GREEN, -1)    # Enabled machine
        curses.init_pair(3, curses.COLOR_RED, -1)      # Disabled machine
        curses.init_pair(4, curses.COLOR_YELLOW, -1)   # Tags / highlights
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN) # Selected cursor

        while True:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            items = self.build_items()
            if self.cursor >= len(items):
                self.cursor = max(0, len(items) - 1)

            # Header
            header = " ◈ Herdr Machine Groups & Sidebar Sync ◈"
            hint_count = f"共 {len(self.machines)} 台 "
            self.stdscr.addstr(0, 0, pad_str(header, w - len(hint_count)), curses.color_pair(1) | curses.A_BOLD)
            self.stdscr.addstr(0, max(0, w - len(hint_count)), hint_count, curses.color_pair(4))
            self.stdscr.addstr(1, 0, "─" * (w - 1), curses.A_DIM)

            # Body
            visible_rows = h - 5
            start_row = 0
            if self.cursor >= visible_rows:
                start_row = self.cursor - visible_rows + 1

            for row_idx in range(visible_rows):
                item_idx = start_row + row_idx
                if item_idx >= len(items):
                    break
                item = items[item_idx]
                y = 2 + row_idx
                is_selected = (item_idx == self.cursor)

                if item["type"] == "group":
                    g_def = item["def"]
                    collapsed = item["collapsed"]
                    arrow = "▶" if collapsed else "▼"
                    tag_str = f"#{g_def.get('tag', 'grp')}"
                    name_str = f"{arrow} [{g_def.get('name')}]"
                    m_count = len(item["machines"])
                    en_count = sum(1 for m in item["machines"] if m.get("enabled", True))
                    stats = f"({en_count}/{m_count} 侧栏可见)"
                    if collapsed:
                        stats += " [已折叠]"

                    line = f" {name_str} {tag_str} {stats}"
                    line_disp = pad_str(line, w - 2)

                    if is_selected:
                        self.stdscr.addstr(y, 0, line_disp[:w-1], curses.color_pair(5) | curses.A_BOLD)
                    else:
                        self.stdscr.addstr(y, 0, line_disp[:w-1], curses.color_pair(1) | curses.A_BOLD)

                elif item["type"] == "machine":
                    m = item["data"]
                    enabled = m.get("enabled", True)
                    dot = "●" if enabled else "○"
                    dot_color = curses.color_pair(2) if enabled else curses.color_pair(3)
                    state_text = "侧栏显示" if enabled else "侧栏隐藏"

                    label = clean_label(m.get("label", ""))
                    target = m.get("target", "")
                    line_text = f"    {dot} {label:<22} ({target:<18}) [{state_text}]"
                    line_disp = pad_str(line_text, w - 2)

                    if is_selected:
                        self.stdscr.addstr(y, 0, line_disp[:w-1], curses.color_pair(5))
                    else:
                        self.stdscr.addstr(y, 0, line_disp[:w-1])
                        self.stdscr.addstr(y, 4, dot, dot_color)

            # Footer / Status
            status_y = h - 2
            if self.status_msg:
                self.stdscr.addstr(status_y, 0, pad_str(f" {self.status_msg}", w - 1), curses.color_pair(4) | curses.A_BOLD)
            else:
                self.stdscr.addstr(status_y, 0, "─" * (w - 1), curses.A_DIM)

            footer = " [Space]折叠并同步侧栏  [f]仅看此组  [a]全部展开  [r]刷新  [q]退出"
            self.stdscr.addstr(h - 1, 0, pad_str(footer, w - 1), curses.A_REVERSE)

            self.stdscr.refresh()

            # Handle Input
            key = self.stdscr.getch()
            self.status_msg = ""

            if key in (curses.KEY_UP, ord('k'), ord('K')):
                if self.cursor > 0:
                    self.cursor -= 1
            elif key in (curses.KEY_DOWN, ord('j'), ord('J')):
                if self.cursor < len(items) - 1:
                    self.cursor += 1
            elif key in (ord(' '), curses.KEY_ENTER, 10, 13, curses.KEY_RIGHT, curses.KEY_LEFT):
                cur_item = items[self.cursor]
                if cur_item["type"] == "group":
                    self.toggle_group_fold(cur_item["id"])
                elif cur_item["type"] == "machine":
                    m = cur_item["data"]
                    new_state = not m.get("enabled", True)
                    self.set_machine_enabled(m["id"], new_state)
                    self.reload()
                    self.status_msg = f"✓ 机器 [{clean_label(m.get('label', ''))}] 已{'显示' if new_state else '隐藏'}"
            elif key in (ord('f'), ord('F')):
                cur_item = items[self.cursor]
                target_gid = cur_item["id"] if cur_item["type"] == "group" else cur_item["group_id"]
                self.focus_group(target_gid)
            elif key in (ord('a'), ord('A')):
                self.show_all()
            elif key in (ord('s'), ord('S')):
                t = sync_sidebar(self.config, self.machines)
                self.reload()
                self.status_msg = f"✓ 侧栏折叠同步完成 (状态变更 {t} 台)"
            elif key in (ord('r'), ord('R')):
                self.reload()
                self.status_msg = "✓ 机器列表已刷新"
            elif key in (ord('q'), ord('Q'), 27):
                break

def main():
    cfg, _ = load_config()
    machines = fetch_machines()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd in ("list", "--list"):
            groups = group_machines(machines, cfg)
            print(json.dumps(groups, ensure_ascii=False, indent=2))
            return
        elif cmd in ("sync", "--sync"):
            t = sync_sidebar(cfg, machines)
            print(f"Sidebar sync complete: {t} machine(s) visibility toggled.")
            return
        elif cmd in ("reset-labels", "--reset-labels"):
            count = reset_all_labels(machines)
            print(f"Reset complete: stripped group prefix from {count} machine(s).")
            return
        elif cmd in ("all", "show-all"):
            for m in machines:
                run_herdr(["machine", "enable", m["id"]])
            for g in cfg.get("groups", []):
                g["collapsed"] = False
            save_config(cfg, get_config_path())
            print(f"Show all: enabled {len(machines)} machines in Herdr sidebar.")
            return
        elif cmd in ("focus", "group") and len(sys.argv) > 2:
            target_tag = sys.argv[2]
            groups = group_machines(machines, cfg)
            target = None
            for g in groups:
                if g["def"].get("id") == target_tag or g["def"].get("tag") == target_tag:
                    target = g
                    break
            if not target:
                print(f"Error: group or tag '{target_tag}' not found.", file=sys.stderr)
                sys.exit(1)
            target_ids = {m["id"] for m in target["machines"]}
            for m in machines:
                action = "enable" if m["id"] in target_ids else "disable"
                run_herdr(["machine", action, m["id"]])
            for g in cfg.get("groups", []):
                g["collapsed"] = (g.get("id") != target["def"].get("id"))
            save_config(cfg, get_config_path())
            print(f"Focused on '{target['def'].get('name')}': {len(target_ids)} machines shown.")
            return
        elif cmd in ("help", "--help", "-h"):
            print("Usage: machine-groups.py [list | sync | reset-labels | show-all | focus <tag> | help]")
            return

    # Run TUI
    curses.wrapper(lambda stdscr: TUI(stdscr).run())

if __name__ == "__main__":
    main()
