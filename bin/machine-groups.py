#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
herdr-machine-groups: Group, tag, fold, and sort Herdr SSH machines with interactive TUI, mouse buttons, and sidebar sync.
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
ENDPOINTS_JSON = os.path.expanduser("~/.local/state/herdr/client/endpoints.json")

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
    """Strip any [Prefix] from label to get raw clean name."""
    return re.sub(r"^\[.*?\]\s*", "", label).strip()

def run_herdr(args):
    cmd = [HERDR_BIN] + args
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return res.stdout.strip()
    except Exception:
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
        "groups": [
            {
                "id": "office",
                "name": "办公与本地设备",
                "tag": "office",
                "patterns": ["*Mac-Mini*", "*ZERO-X*", "*local*", "*lan*"],
                "collapsed": False
            },
            {
                "id": "test",
                "name": "测试节点",
                "tag": "test",
                "patterns": ["*测试机*", "*test*"],
                "collapsed": False
            },
            {
                "id": "cloud",
                "name": "云端服务器",
                "tag": "cloud",
                "patterns": ["*腾讯云*", "tx-*", "*aliyun*", "*aws*", "*server*"],
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
    except Exception:
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

def apply_endpoints_order(ordered_machine_ids):
    """Write exact machine order into endpoints.json so Herdr sidebar matches."""
    if not os.path.exists(ENDPOINTS_JSON):
        return False
    try:
        with open(ENDPOINTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        ssh_list = data.get("ssh", [])
        m_map = {m["id"]: m for m in ssh_list}

        new_ssh = [m_map[mid] for mid in ordered_machine_ids if mid in m_map]
        used = set(ordered_machine_ids)
        for m in ssh_list:
            if m["id"] not in used:
                new_ssh.append(m)

        data["ssh"] = new_ssh
        with open(ENDPOINTS_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

def sort_and_sync_endpoints(config, machines=None, mode="group"):
    """
    Sort machines according to mode and apply to endpoints.json:
    - 'group': by group definitions order, preserving existing order in group
    - 'name': by group definitions order, alphabetically A-Z inside each group
    - 'status': by group definitions order, active/enabled first inside each group
    - 'global-name': pure alphabetical A-Z regardless of groups
    """
    if machines is None:
        machines = fetch_machines()

    if mode == "global-name":
        sorted_m = sorted(machines, key=lambda m: clean_label(m.get("label", "")).lower())
        ordered_ids = [m["id"] for m in sorted_m]
    else:
        groups = group_machines(machines, config)
        ordered_ids = []
        for g in groups:
            m_list = list(g["machines"])
            if mode == "name":
                m_list.sort(key=lambda m: clean_label(m.get("label", "")).lower())
            elif mode == "status":
                m_list.sort(key=lambda m: (not m.get("enabled", True), clean_label(m.get("label", "")).lower()))
            for m in m_list:
                ordered_ids.append(m["id"])

    apply_endpoints_order(ordered_ids)
    return len(ordered_ids)

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

class TUI:
    SORT_MODES = ["group", "name", "status", "global-name"]
    SORT_LABELS = {
        "group": "分组默认顺序",
        "name": "组内名称 A-Z",
        "status": "组内活跃状态优先",
        "global-name": "全局名称 A-Z"
    }

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.config, self.config_path = load_config()
        self.machines = fetch_machines()
        self.cursor = 0
        self.status_msg = ""
        self.sort_mode_idx = 0
        self.collapsed_map = {g.get("id"): g.get("collapsed", False) for g in self.config.get("groups", [])}
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

        for g in self.config.get("groups", []):
            if g.get("id") == g_id:
                g["collapsed"] = new_val
        save_config(self.config, self.config_path)

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

    def move_item(self, direction, target_idx=None):
        """Move selected group or machine up (-1) or down (+1) and sync order to endpoints.json."""
        items = self.build_items()
        idx_to_use = self.cursor if target_idx is None else target_idx
        if idx_to_use >= len(items):
            return
        cur_item = items[idx_to_use]

        if cur_item["type"] == "group":
            g_id = cur_item["id"]
            if g_id == "ungrouped":
                self.status_msg = "未分组不可调序"
                return
            groups_list = self.config.get("groups", [])
            idx = next((i for i, g in enumerate(groups_list) if g.get("id") == g_id), -1)
            if idx == -1:
                return
            new_idx = idx + direction
            if 0 <= new_idx < len(groups_list):
                groups_list[idx], groups_list[new_idx] = groups_list[new_idx], groups_list[idx]
                save_config(self.config, self.config_path)
                sort_and_sync_endpoints(self.config, self.machines, mode="group")
                self.reload()
                new_items = self.build_items()
                for ni, itm in enumerate(new_items):
                    if itm["type"] == "group" and itm["id"] == g_id:
                        self.cursor = ni
                        break
                self.status_msg = f"✓ 分组 [{cur_item['def'].get('name')}] 已{'上移' if direction < 0 else '下移'}，侧栏已同步"
            else:
                self.status_msg = "已在边界，无法继续移动"

        elif cur_item["type"] == "machine":
            m_id = cur_item["data"]["id"]
            m_label = clean_label(cur_item["data"].get("label", ""))
            idx = next((i for i, m in enumerate(self.machines) if m.get("id") == m_id), -1)
            if idx == -1:
                return
            new_idx = idx + direction
            if 0 <= new_idx < len(self.machines):
                self.machines[idx], self.machines[new_idx] = self.machines[new_idx], self.machines[idx]
                apply_endpoints_order([m["id"] for m in self.machines])
                self.reload()
                new_items = self.build_items()
                for ni, itm in enumerate(new_items):
                    if itm["type"] == "machine" and itm["data"]["id"] == m_id:
                        self.cursor = ni
                        break
                self.status_msg = f"✓ 机器 [{m_label}] 已{'上移' if direction < 0 else '下移'}，侧栏已同步"
            else:
                self.status_msg = "已在边界，无法继续移动"

    def cycle_sort(self):
        """Cycle through sorting modes and immediately sort sidebar."""
        self.sort_mode_idx = (self.sort_mode_idx + 1) % len(self.SORT_MODES)
        mode = self.SORT_MODES[self.sort_mode_idx]
        mode_label = self.SORT_LABELS[mode]
        sort_and_sync_endpoints(self.config, self.machines, mode=mode)
        self.reload()
        self.status_msg = f"✓ 已应用排序：[{mode_label}]，侧栏已同步"

    def run(self):
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)
        curses.use_default_colors()

        # Enable mouse events (reporting button clicks & coordinates)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        try:
            curses.mouseinterval(50)
        except Exception:
            pass

        # Send xterm mouse protocol escapes to terminal
        sys.stdout.write("\033[?1000h\033[?1002h\033[?1006h")
        sys.stdout.flush()

        curses.init_pair(1, curses.COLOR_CYAN, -1)     # Group header
        curses.init_pair(2, curses.COLOR_GREEN, -1)    # Enabled machine
        curses.init_pair(3, curses.COLOR_RED, -1)      # Disabled machine
        curses.init_pair(4, curses.COLOR_YELLOW, -1)   # Tags / button highlights
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN) # Selected cursor
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE) # Clickable button style

        try:
            while True:
                self.stdscr.clear()
                h, w = self.stdscr.getmaxyx()
                items = self.build_items()
                if self.cursor >= len(items):
                    self.cursor = max(0, len(items) - 1)

                btn_up_col = max(10, w - 9)
                btn_down_col = max(14, w - 5)
                text_max_w = max(10, btn_up_col - 2)

                # Header
                header = " ◈ Herdr Machine Groups & Clusters ◈"
                hint_count = f"共 {len(self.machines)} 台机器 "
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
                        line_disp = pad_str(line, text_max_w)

                        if is_selected:
                            self.stdscr.addstr(y, 0, line_disp[:text_max_w], curses.color_pair(5) | curses.A_BOLD)
                        else:
                            self.stdscr.addstr(y, 0, line_disp[:text_max_w], curses.color_pair(1) | curses.A_BOLD)

                    elif item["type"] == "machine":
                        m = item["data"]
                        enabled = m.get("enabled", True)
                        dot = "●" if enabled else "○"
                        dot_color = curses.color_pair(2) if enabled else curses.color_pair(3)
                        state_text = "侧栏显示" if enabled else "侧栏隐藏"

                        label = clean_label(m.get("label", ""))
                        target = m.get("target", "")
                        line_text = f"    {dot} {label:<20} ({target:<16}) [{state_text}]"
                        line_disp = pad_str(line_text, text_max_w)

                        if is_selected:
                            self.stdscr.addstr(y, 0, line_disp[:text_max_w], curses.color_pair(5))
                        else:
                            self.stdscr.addstr(y, 0, line_disp[:text_max_w])
                            self.stdscr.addstr(y, 4, dot, dot_color)

                    # Draw clickable [▲] [▼] buttons
                    self.stdscr.addstr(y, btn_up_col, "[▲]", curses.color_pair(4) | curses.A_BOLD)
                    self.stdscr.addstr(y, btn_down_col, "[▼]", curses.color_pair(4) | curses.A_BOLD)

                # Footer / Status
                status_y = h - 2
                if self.status_msg:
                    self.stdscr.addstr(status_y, 0, pad_str(f" {self.status_msg}", w - 1), curses.color_pair(4) | curses.A_BOLD)
                else:
                    self.stdscr.addstr(status_y, 0, "─" * (w - 1), curses.A_DIM)

                footer = " [鼠标点击▲/▼]调序  [K/J]键盘调序  [Space]折叠侧栏  [o]切换排序  [f]仅看此组  [q]退出"
                self.stdscr.addstr(h - 1, 0, pad_str(footer, w - 1), curses.A_REVERSE)

                self.stdscr.refresh()

                # Handle Input
                key = self.stdscr.getch()
                self.status_msg = ""

                if key == curses.KEY_MOUSE:
                    try:
                        _, mx, my, _, bstate = curses.getmouse()
                        if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED):
                            row_idx = my - 2
                            if 0 <= row_idx < visible_rows:
                                target_item_idx = start_row + row_idx
                                if target_item_idx < len(items):
                                    # Clicked [▲]
                                    if btn_up_col <= mx <= btn_up_col + 2:
                                        self.cursor = target_item_idx
                                        self.move_item(-1, target_item_idx)
                                    # Clicked [▼]
                                    elif btn_down_col <= mx <= btn_down_col + 2:
                                        self.cursor = target_item_idx
                                        self.move_item(1, target_item_idx)
                                    else:
                                        self.cursor = target_item_idx
                                        # If clicked near arrow on group header, toggle fold
                                        if items[target_item_idx]["type"] == "group" and mx <= 6:
                                            self.toggle_group_fold(items[target_item_idx]["id"])
                    except Exception:
                        pass
                elif key in (curses.KEY_UP, ord('k')):
                    if self.cursor > 0:
                        self.cursor -= 1
                elif key in (curses.KEY_DOWN, ord('j')):
                    if self.cursor < len(items) - 1:
                        self.cursor += 1
                elif key in (ord('K'), ord('[')):
                    self.move_item(-1)
                elif key in (ord('J'), ord(']')):
                    self.move_item(1)
                elif key in (ord('o'), ord('O')):
                    self.cycle_sort()
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
                elif key in (ord('r'), ord('R')):
                    self.reload()
                    self.status_msg = "✓ 机器列表已刷新"
                elif key in (ord('q'), ord('Q'), 27):
                    break
        finally:
            # Disable mouse tracking on exit
            sys.stdout.write("\033[?1000l\033[?1002l\033[?1006l")
            sys.stdout.flush()

def main():
    cfg, _ = load_config()
    machines = fetch_machines()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd in ("list", "--list"):
            groups = group_machines(machines, cfg)
            print(json.dumps(groups, ensure_ascii=False, indent=2))
            return
        elif cmd in ("sort", "--sort"):
            mode = "group"
            if len(sys.argv) > 2:
                arg = sys.argv[2].lstrip("-")
                if arg in ("name", "status", "global-name"):
                    mode = arg
            count = sort_and_sync_endpoints(cfg, machines, mode=mode)
            print(f"Sort complete: reordered {count} machine(s) in Herdr sidebar (mode: {mode}).")
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
            print("Usage: machine-groups.py [list | sort [group|name|status|global-name] | show-all | focus <tag> | help]")
            return

    # Run TUI
    curses.wrapper(lambda stdscr: TUI(stdscr).run())

if __name__ == "__main__":
    main()
