#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ROM Classic 組隊輪替
====================

讓小號自己申請進隊長的隊伍，今日戰鬥次數打滿 10000 就自己離隊，
把位置讓給下一隻。程式每隔幾分鐘巡一輪，直到所有小號都打滿。

每隻小號每輪做的事：
    按 T 看隊伍狀態
      ├─ 看到「離開隊伍」= 在隊裡 → 點頭像看戰鬥次數
      │       ├─ 紅字 10000/10000 → 離開隊伍 → 標記完成
      │       └─ 沒滿 → 什麼都不做
      └─ 看到「創建隊伍」= 不在隊裡 → 點頭像看戰鬥次數
              ├─ 已經滿了 → 標記完成
              └─ 沒滿，而且隊伍有空位 → 按 O → ❤ 分頁 → 第一個好友 → 旗子申請

「隊伍有空位」是程式自己算的：隊伍上限 6 減掉隊長 = 5 隻小號，
目前在隊裡的隻數由每輪巡查得知。圖上的「可申請 5/5」看起來是每日申請次數上限，
所以絕對不能沒空位還一直申請。

前置條件：
    * 小號跟隊長在同一張地圖（這程式不會移動角色）
    * 每隻小號的好友「❤ 我的最愛」裡只放隊長一個人
    * 校正分頁抓好四張模板和四個位置（見 GUI「⑤ 組隊輪替」）

用法：
    python rom_party.py                 # 用 config.json 的設定持續巡邏
    python rom_party.py once            # 只巡一輪就停，用來測試
    python rom_party.py once 3          # 只看第 3 個視窗一次
"""

import sys
import time

import pyautogui

import rom_daily as rd
from rom_daily import (back_to_main, click_at, click_box, find_one, grab, has,
                       wait_for, wait_stable, wait_until, dump_fail, on_main)

# ---------------------------------------------------------------------------
# 設定（config.json 有寫就蓋掉）
# ---------------------------------------------------------------------------

__version__ = "2026.11.05"

PARTY_KEY = "t"                  # 隊伍面板
FRIEND_KEY = "o"                 # 好友面板
PARTY_SIZE = 6                   # 隊伍上限（含隊長）
LEADER_WINDOW = 0                # 隊長是第幾個視窗；0 = 隊長不在這台電腦上
ALT_WINDOWS = None               # 小號視窗編號清單；None = 除了隊長以外全部
INTERVAL_MIN = 5.0               # 每輪之間隔幾分鐘

# 以下位置都是相對工作視窗左上角，數字是依截圖粗估的，請用 GUI 校正確認
P_AVATAR = (45, 75)              # 左上角自己的頭像
P_FAV_TAB = (553, 84)            # 好友面板的 ❤ 分頁
P_FRIEND_FIRST = (511, 147)      # ❤ 分頁第一個好友的頭像
P_APPLY_FLAG = (393, 224)        # 好友小視窗裡的旗子（申請入隊）
P_PARTY_BTN = None               # 主畫面上方「隊伍」按鈕；T 沒反應時改點它（模擬器用）
P_MORE_BTN = None                # 主畫面上方「更多」按鈕；沒快捷鍵時好友藏在它底下
P_FRIEND_BTN = None              # 「更多」展開後的「好友」按鈕；沒快捷鍵時改點它

# 模板：count_full.png 紅字 10000/10000、leave_party.png 離開隊伍、
#       create_party.png 創建隊伍、confirm_ok.png 綠色確定

STATE_WAIT, STATE_IN, STATE_DONE, STATE_ERR = "等待入隊", "隊伍中", "已打滿", "異常"


def _load():
    """組隊的設定在共用 config；四個位置在目前環境的 config。"""
    global PARTY_KEY, FRIEND_KEY, PARTY_SIZE, LEADER_WINDOW, ALT_WINDOWS, INTERVAL_MIN
    global P_AVATAR, P_FAV_TAB, P_FRIEND_FIRST, P_APPLY_FLAG, P_PARTY_BTN, P_FRIEND_BTN, P_MORE_BTN
    shared = rd._read_json(rd.SHARED_CONFIG_PATH)
    PARTY_KEY = str(shared.get("party_key", "t"))
    FRIEND_KEY = str(shared.get("friend_key", "o"))
    PARTY_SIZE = int(shared.get("party_size", 6))
    LEADER_WINDOW = int(shared.get("party_leader_window", 0))
    INTERVAL_MIN = float(shared.get("party_interval_min", 5.0))
    ALT_WINDOWS = [int(n) for n in shared["party_alt_windows"]] \
        if shared.get("party_alt_windows") else None

    prof = rd._read_json(rd.CONFIG_PATH)
    defaults = {"party_avatar": (45, 75), "party_fav_tab": (553, 84),
                "party_friend_first": (511, 147), "party_apply_flag": (393, 224),
                "party_btn": None, "friend_btn": None, "more_btn": None}
    if rd.ACTIVE_PROFILE != "官方":            # 官方以外的環境沒有可信的預設座標
        defaults = {k: None for k in defaults}
    for key, name in (("party_avatar", "P_AVATAR"), ("party_fav_tab", "P_FAV_TAB"),
                      ("party_friend_first", "P_FRIEND_FIRST"),
                      ("party_apply_flag", "P_APPLY_FLAG"),
                      ("party_btn", "P_PARTY_BTN"), ("friend_btn", "P_FRIEND_BTN"),
                      ("more_btn", "P_MORE_BTN")):
        val = prof.get(key) or defaults[key]
        globals()[name] = tuple(val) if val else None


_load()


# ---------------------------------------------------------------------------
# 三個基本動作：看隊伍狀態、看戰鬥次數、申請入隊
# ---------------------------------------------------------------------------

def party_status():
    """按 T 看隊伍狀態。回傳 'in' / 'out' / None（看不懂）。面板會留著開。"""
    if rd.HOTKEYS:
        pyautogui.press(PARTY_KEY)
        rd.nap(0.6)
        wait_stable(rd.T_PANEL_MAX)
    if on_main() and P_PARTY_BTN:                  # 沒快捷鍵（或沒反應）→ 點螢幕上的隊伍按鈕
        click_at(P_PARTY_BTN[0], P_PARTY_BTN[1], wait=rd.T_PANEL_MAX)
    deadline = time.time() + 5.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        screen = grab()
        if find_one(screen, "leave_party.png"):
            return "in"
        if find_one(screen, "create_party.png"):
            return "out"
        time.sleep(0.4)
    return None


def count_is_full():
    """點頭像看今日戰鬥次數。回傳 True 滿了 / False 沒滿 / None 面板沒開。"""
    if not on_main():
        back_to_main()
    if not P_AVATAR:
        return None
    click_at(P_AVATAR[0], P_AVATAR[1], wait=rd.T_PANEL_MAX)
    # 面板開了嗎：看得到紅字就是滿；否則至少要離開主畫面才算面板有開
    deadline = time.time() + 4.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        screen = grab()
        if find_one(screen, "count_full.png"):
            back_to_main()
            return True
        if not on_main(screen):
            break
        time.sleep(0.4)
    else:
        return None
    wait_stable(1.5)
    full = find_one(grab(), "count_full.png") is not None
    back_to_main()
    return full


def leave_party():
    """在隊伍面板開著的狀態下點離開隊伍 → 確定。回傳有沒有成功離開。"""
    btn = find_one(grab(), "leave_party.png")
    if not btn:
        return False
    click_box(btn)
    ok = wait_for("confirm_ok.png", timeout=4.0)
    if ok:
        click_box(ok)
    wait_stable(2.0)
    back_to_main()
    # 再按一次 T 確認真的不在隊裡了
    st = party_status()
    back_to_main()
    return st == "out"


def apply_party():
    """按 O → ❤ 分頁 → 第一個好友 → 旗子。回傳申請後有沒有真的進隊。"""
    if not on_main():
        back_to_main()
    if rd.HOTKEYS:
        pyautogui.press(FRIEND_KEY)
        rd.nap(0.6)
        wait_stable(rd.T_PANEL_MAX)
    if on_main() and P_FRIEND_BTN:                 # 沒快捷鍵（或沒反應）→ 更多 → 好友
        if rd.too_close(P_MORE_BTN, P_FRIEND_BTN):
            print("  「好友」位置跟「更多」是同一點，抓錯了：校正頁先手動點開「更多」再抓「好友」")
            back_to_main()
            return False
        if P_MORE_BTN and not rd.open_more_menu():   # 選單沒展開就不點，免得點到主畫面別的東西
            print("  點了「更多」但選單沒展開（遊戲可能太卡）")
            back_to_main()
            return False
        pt = rd.menu_item_point("menu_friend.png", P_FRIEND_BTN, "好友")
        if not pt:
            back_to_main()
            return False
        click_at(pt[0], pt[1], wait=rd.T_PANEL_MAX)
    if not (P_FAV_TAB and P_FRIEND_FIRST and P_APPLY_FLAG):
        back_to_main()
        return False
    click_at(P_FAV_TAB[0], P_FAV_TAB[1])
    click_at(P_FRIEND_FIRST[0], P_FRIEND_FIRST[1])
    click_at(P_APPLY_FLAG[0], P_APPLY_FLAG[1])
    wait_stable(2.0)
    back_to_main()
    # 自由隊伍是直接進的，馬上按 T 看有沒有成功
    st = party_status()
    back_to_main()
    return st == "in"


# ---------------------------------------------------------------------------
# 巡一隻小號
# ---------------------------------------------------------------------------

def visit(idx, hwnd, state, slots_free):
    """處理一隻小號。回傳 (新狀態, 訊息, 這次有沒有佔用一個空位)。"""
    orig = rd.get_rect(hwnd)
    try:
        rd.normalize_window(hwnd)
        if on_main():
            rd.wake_up()                        # 省電模式：先點一下叫醒
        if not on_main() and not back_to_main():
            return STATE_ERR, f"不在主畫面（{dump_fail(f'party{idx:02d}_start')}）", False

        st = party_status()
        if st is None:
            shot = dump_fail(f"party{idx:02d}_T")
            back_to_main()
            return STATE_ERR, f"按 T 後看不懂畫面（{shot}）", False
        back_to_main()

        full = count_is_full()
        if full is None:
            return STATE_ERR, f"頭像面板沒開（{dump_fail(f'party{idx:02d}_avatar')}）", False

        if st == "in":
            if not full:
                return STATE_IN, "在隊裡，還沒打滿", False
            party_status()                      # 重開隊伍面板準備離開
            if leave_party():
                return STATE_DONE, "打滿了，已離隊", False
            shot = dump_fail(f"party{idx:02d}_leave")
            back_to_main()
            return STATE_IN, f"打滿了但離隊失敗（{shot}）", False

        # 不在隊裡
        if full:
            return STATE_DONE, "已打滿（不在隊裡）", False
        if slots_free <= 0:
            return STATE_WAIT, "等空位", False
        if apply_party():
            return STATE_IN, "已申請並進隊", True
        return STATE_WAIT, "申請了但沒進隊（可能隊伍剛好滿了）", False

    except (pyautogui.FailSafeException, rd.Aborted):
        raise
    except Exception as e:
        try:
            back_to_main()
        except Exception:
            pass
        return STATE_ERR, f"發生錯誤：{e}", False
    finally:
        try:
            rd.move_window(hwnd, *orig)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 主迴圈
# ---------------------------------------------------------------------------

def pick_alts(hwnds):
    if ALT_WINDOWS:
        return [n for n in ALT_WINDOWS if 1 <= n <= len(hwnds) and n != LEADER_WINDOW]
    return [n for n in range(1, len(hwnds) + 1) if n != LEADER_WINDOW]


def _check_ready(who=""):
    """目前載入的那一套（官方或雷電）組隊用的模板、位置齊不齊。"""
    tag = f"【{who}】" if who else ""
    need = ["leave_party.png", "create_party.png", "count_full.png", "confirm_ok.png"]
    missing = [f for f in need if not has(f)]
    if missing:
        print(f"{tag}缺少模板：" + "、".join(missing) + "，請到校正分頁「組隊輪替」那組抓")
        return False
    if not (P_AVATAR and P_FAV_TAB and P_FRIEND_FIRST and P_APPLY_FLAG):
        print(f"{tag}組隊的四個位置還沒校正完（頭像、❤ 分頁、第一個好友、旗子）")
        return False
    if not rd.HOTKEYS and not (P_PARTY_BTN and P_FRIEND_BTN):
        print(f"{tag}這個環境沒有快捷鍵，請在校正分頁抓「隊伍按鈕」和「好友按鈕」的位置")
        return False
    return True


def _use(hwnd):
    """切到這個視窗那一套設定（自動模式下官方、雷電各用各的），組隊的位置也重讀。"""
    rd.use_profile(rd.kind_of(hwnd))
    _load()


def run(once=False, only=None, leader=None, alts=None):
    """leader：隊長的視窗（None = 隊長不在這台電腦）；alts：小號視窗清單。

    GUI 會從彈窗把選好的視窗直接傳進來；沒傳（命令列）就照舊用設定裡的視窗編號。
    """
    home = rd.ACTIVE_PROFILE
    try:
        _run(once, only, leader, alts)
    finally:
        rd.use_profile(home)
        _load()


def _run(once, only, leader, alts):
    if alts is None:                               # 命令列：照舊用編號
        hwnds = rd.find_windows()
        if not hwnds:
            print("找不到遊戲視窗")
            return
        nums = [only] if only else pick_alts(hwnds)
        alts = [hwnds[n - 1] for n in nums if 1 <= n <= len(hwnds)]
        if 1 <= LEADER_WINDOW <= len(hwnds):
            leader = hwnds[LEADER_WINDOW - 1]
    if not alts:
        print("沒有小號視窗可以巡")
        return

    kinds = sorted({rd.kind_of(h) for h in alts}, key=lambda k: rd.PROFILE_NAMES.index(k))
    for k in kinds:
        rd.use_profile(k)
        _load()
        if not _check_ready(k if rd.RUN_MODE == rd.AUTO_MODE else ""):
            return

    max_alts = max(1, PARTY_SIZE - (1 if leader else 0))
    states = {h: STATE_WAIT for h in alts}
    names = ([rd.window_label(h) for h in alts] if rd.RUN_MODE == rd.AUTO_MODE
             else [_num(h) for h in alts])        # 固定模式照舊印編號
    who = f"隊長 {rd.window_label(leader)}，" if leader and rd.RUN_MODE == rd.AUTO_MODE else ""
    print(f"{who}小號 {names}，隊伍上限 {PARTY_SIZE}（可容納 {max_alts} 隻小號），"
          f"每 {INTERVAL_MIN:g} 分鐘巡一輪")

    try:
        _run_loop(alts, states, max_alts, once)
    except rd.Aborted:
        print("\n已中止，視窗已還原。")


def _num(hwnd):
    """這個視窗現在是第幾號（開關視窗會變，所以每次現算）。不在了回傳 0。"""
    hwnds = rd.find_windows()
    return hwnds.index(hwnd) + 1 if hwnd in hwnds else 0


def _run_loop(alts, states, max_alts, once):
    import win32gui
    rnd = 0
    while True:
        rnd += 1
        print(f"\n===== 第 {rnd} 輪 {time.strftime('%H:%M:%S')} =====")
        in_party = sum(1 for s in states.values() if s == STATE_IN)
        for h in alts:
            if rd.ABORT:
                print("已中止")
                return
            if states[h] == STATE_DONE:
                continue
            n = _num(h)
            if not n or not win32gui.IsWindow(h):
                states[h] = STATE_ERR
                print(f"  {rd.window_label(h) if win32gui.IsWindow(h) else '某個視窗'}：不見了")
                continue
            _use(h)
            slots_free = max_alts - in_party
            new, msg, took = visit(n, h, states[h], slots_free)
            if states[h] == STATE_IN and new != STATE_IN:
                in_party -= 1
            if took:
                in_party += 1
            states[h] = new
            print(f"  {rd.win_title(n, h, pad=True)}：{new}　{msg}")

        summary = {}
        for s in states.values():
            summary[s] = summary.get(s, 0) + 1
        print("  狀態：" + "、".join(f"{k} {v}" for k, v in summary.items()))

        if all(s == STATE_DONE for s in states.values()):
            print("\n所有小號都打滿了，結束。")
            return
        if once:
            return
        # 可中斷的等待
        end = time.time() + INTERVAL_MIN * 60
        while time.time() < end:
            if rd.ABORT:
                print("已中止")
                return
            time.sleep(1)


if __name__ == "__main__":
    rd.enable_dpi_awareness()
    rd.start_stop_hotkey()
    args = sys.argv[1:]
    num = next((int(a) for a in args if a.isdigit()), None)
    run(once=("once" in args), only=num)
