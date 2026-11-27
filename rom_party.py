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

import os
import sys
import time

import pyautogui

import rom_daily as rd
from rom_daily import (back_to_main, click_at, click_box, find_one, grab, has,
                       wait_for, wait_stable, wait_until, dump_fail, on_main)

# ---------------------------------------------------------------------------
# 設定（config.json 有寫就蓋掉）
# ---------------------------------------------------------------------------

__version__ = "2026.11.27"

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

# 燃料輪替（鐵匠每天 2000 燃料，三隻角色輪流進打手的隊伍吸）
FUEL_MAX = 5                     # 同時最多幾隻在吸（隊伍 6 人含打手）
FUEL_GAP = 20.0                  # 同一個視窗至少隔幾秒才再看一次
FUEL_ACTION_GAP = 2.0            # 燃料輪替：每點一下、每按一個鍵之後至少停幾秒（使用者要求：動作太快，每個都等 2 秒）
FUEL_FIRST_WAIT = 60.0           # 進隊跟隨後，等幾秒才第一次開對話框看（使用者要求：先讓它打一陣子）
BAG_KEY = "b"                    # 包包（官方）
P_CHAR_SLOTS = [None, None, None]  # 選角畫面左邊 3 個頭像（第 1 個是本尊）
P_CHAT_OPEN = None               # 主畫面左下角的對話框
P_BAG_BTN = None                 # 主畫面上方「包包」按鈕（沒快捷鍵時）
P_BAG_FAV = None                 # 包包裡的愛心分頁
P_BAG_SCROLL = None              # 包包物品格子區的正中間（燃料不在第一頁時從這裡上下拖來找）

# 模板：count_full.png 紅字 10000/10000、leave_party.png 離開隊伍、
#       create_party.png 創建隊伍、confirm_ok.png 綠色確定

STATE_WAIT, STATE_IN, STATE_DONE, STATE_ERR = "等待入隊", "隊伍中", "已打滿", "異常"


def _load():
    """組隊的設定在共用 config；四個位置在目前環境的 config。"""
    global PARTY_KEY, FRIEND_KEY, PARTY_SIZE, LEADER_WINDOW, ALT_WINDOWS, INTERVAL_MIN
    global P_AVATAR, P_FAV_TAB, P_FRIEND_FIRST, P_APPLY_FLAG, P_PARTY_BTN, P_FRIEND_BTN, P_MORE_BTN
    global FUEL_MAX, FUEL_GAP, BAG_KEY, P_CHAR_SLOTS, P_CHAT_OPEN, P_BAG_BTN, P_BAG_FAV, P_BAG_SCROLL
    shared = rd._read_json(rd.SHARED_CONFIG_PATH)
    FUEL_MAX = int(shared.get("fuel_max", 5))
    FUEL_GAP = float(shared.get("fuel_gap", 20.0))
    BAG_KEY = str(shared.get("bag_key", "b"))
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
    P_CHAR_SLOTS = [tuple(prof[k]) if prof.get(k) else None for k in ("char_slot_1", "char_slot_2", "char_slot_3")]
    P_CHAT_OPEN = tuple(prof["chat_open"]) if prof.get("chat_open") else None
    bag = prof.get("bag_btn") or ((611, 45) if rd.ACTIVE_PROFILE == "雷電" else None)   # 雷電上方「包包」照截圖量的
    P_BAG_BTN = tuple(bag) if bag else None
    P_BAG_FAV = tuple(prof["bag_fav_tab"]) if prof.get("bag_fav_tab") else None
    P_BAG_SCROLL = tuple(prof["bag_scroll"]) if prof.get("bag_scroll") else None


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
        rd.step("⚠ 還沒校正「左上角頭像」位置，沒辦法看本尊的戰鬥次數")
        return None
    rd.step("本尊：點左上角頭像，看今天戰鬥次數有沒有 10000")
    click_at(P_AVATAR[0], P_AVATAR[1], wait=rd.T_PANEL_MAX)
    # 面板開了嗎：看得到紅字就是滿；否則至少要離開主畫面才算面板有開
    deadline = time.time() + 4.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        screen = grab()
        if find_one(screen, "count_full.png"):
            rd.step("戰鬥次數 10000（紅字）→ 打滿了")
            back_to_main()
            return True
        if not on_main(screen):
            break
        time.sleep(0.4)
    else:
        rd.step("⚠ 點了頭像但角色面板沒打開")
        return None
    wait_stable(1.5)
    full = find_one(grab(), "count_full.png") is not None
    rd.step("戰鬥次數 10000（紅字）→ 打滿了" if full else "戰鬥次數還沒 10000 → 繼續")
    back_to_main()
    return full


def leave_party():
    """在隊伍面板開著的狀態下點離開隊伍 → 確定。回傳有沒有成功離開。"""
    btn = find_one(grab(), "leave_party.png")
    if not btn:
        rd.step("隊伍面板裡找不到「離開隊伍」")
        return False
    click_box(btn)
    ok = wait_for("confirm_ok.png", timeout=4.0)
    if not ok:
        rd.step(f"按了「離開隊伍」但看不到綠色「確定」（confirm_ok 可能要重抓；{dump_fail('fuel_leave_confirm')}）")
    else:
        # 使用者實測：卡在「是否要退出當前組隊？」——對話框剛跳出來就點，遊戲沒收到。
        # 點完確認對話框有沒有消失，還在就再點，最多 3 次（跟「開始遊戲」同一招）。
        for n in range(1, 4):
            click_box(ok, wait=0.5)
            gone = wait_until(lambda sc: find_one(sc, "confirm_ok.png") is None, 2.5)
            if gone:
                if n > 1:
                    rd.step(f"「確定」點了 {n} 次才離隊")
                break
            ok = find_one(grab(), "confirm_ok.png") or ok
            if n < 3:
                rd.step(f"點了「確定」對話框還在，再點一次（第 {n + 1} 次）")
        else:
            rd.step(f"「確定」點了 3 次對話框還在（{dump_fail('fuel_leave_stuck')}）")
    wait_stable(2.0)
    back_to_main()
    # 再按一次 T 確認真的不在隊裡了
    st = party_status()
    back_to_main()
    return st == "out"


FAV_LINE_MIN = 30                # ❤ 底下一列有幾個藍點以上算「有底線」（選中時量到 54、沒選中 0）


def _fav_underline(screen):
    """直接看 ❤ 分頁底下有沒有那條藍色底線（被選中的分頁才有）。不用模板，每台電腦都一樣。
    實測（官方）：選中的分頁中心往下約 21～24 點有一條 4 點高、約 54 點寬的藍線（B>150、B−R>80）；沒選中的完全沒有藍色。"""
    if not P_FAV_TAB or screen is None:
        return False
    try:
        x, y = P_FAV_TAB
        h, w = screen.shape[:2]
        x0, x1 = max(0, x - 30), min(w, x + 30)
        for yy in range(max(0, y + 8), min(h, y + 40)):
            row = screen[yy, x0:x1].astype("int16")        # BGR
            b, r = row[:, 0], row[:, 2]
            if int(((b > 150) & (b - r > 80)).sum()) >= FAV_LINE_MIN:
                return True
    except Exception:
        pass
    return False


def _fav_selected(screen=None):
    """好友面板現在是不是在 ❤ 分頁：fav_tab_on.png 比得到（門檻 0.9、在 ❤ 附近），或 ❤ 底下有藍色底線。

    朋友用使用者分享的 fav_tab_on.png 在他電腦上比不到 → 明明切過去了卻點 3 次就放棄不申請（2026.11.11b）。
    現在兩種任一個成立就算；都不成立才算沒切過去。"""
    screen = grab() if screen is None else screen
    if has("fav_tab_on.png"):
        for b in rd.find_all(screen, "fav_tab_on.png", threshold=0.9):
            cx, cy = b[0] + b[2] // 2, b[1] + b[3] // 2
            if not P_FAV_TAB or (abs(cx - P_FAV_TAB[0]) < 60 and abs(cy - P_FAV_TAB[1]) < 60):
                return True
    return _fav_underline(screen)


def open_fav_tab():
    """點 ❤ 分頁，並確認真的切過去了（使用者實測：滑鼠指到愛心但沒切過去，
    剛好打手在 All 也排第一才沒出事）。最多點 3 次，切不過去就回傳 False（不申請）。
    確認方法：fav_tab_on.png 或 ❤ 底下的藍色底線（不用模板也能確認）。"""
    for n in range(1, 4):
        click_at(P_FAV_TAB[0], P_FAV_TAB[1])
        deadline = time.time() + 3.0 * max(0.5, rd.SLOW)
        while time.time() < deadline:
            if _fav_selected():
                if n > 1:
                    rd.step(f"點了 {n} 次才切到 ❤ 分頁")
                return True
            time.sleep(0.4)
        if n < 3:
            rd.step(f"點了 ❤ 但沒切過去，再點一次（第 {n + 1} 次）")
    rd.step("點了 3 次還是認不出切到 ❤ 分頁（❤ 底下沒看到藍線，圖也比不到），這次不申請"
            f"（如果其實有切過去：到校正頁重抓「組隊輪替」的 ❤ 分頁位置，點在愛心正中間；{dump_fail('friend_fav')}）")
    return False


def close_friend_panel():
    """點好友面板右上角的 ✕ 關掉（它跟其他面板的關閉鈕長得不一樣，一般的回主畫面關不掉）。
    最多點 3 次，看不到 ✕ 就是關掉了；最後再回主畫面收尾（申請後的小視窗之類）。"""
    if has("friend_close.png"):
        for _ in range(3):
            b = find_one(grab(), "friend_close.png")
            if not b:
                break
            click_box(b, wait=rd.T_PANEL_MAX)
    back_to_main()


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
    if not open_fav_tab():
        close_friend_panel()
        return False
    click_at(P_FRIEND_FIRST[0], P_FRIEND_FIRST[1])
    click_at(P_APPLY_FLAG[0], P_APPLY_FLAG[1])
    wait_stable(2.0)
    close_friend_panel()
    # 自由隊伍是直接進的，但遊戲要一點時間。以前馬上看一次就下結論 → 朋友實測：說「沒進去，1 分鐘後再試」，
    # 其實已經進隊了（1 分鐘後才跟隨）。現在最多看 3 次、前後約 6 秒，看到進隊就繼續（2026.11.11d）。
    deadline = time.time() + 6.0 * max(0.5, rd.SLOW)
    n = 0
    while True:
        n += 1
        st = party_status()
        back_to_main()
        if st == "in":
            if n > 1:
                rd.step(f"看了 {n} 次才確認進隊（遊戲加入隊伍比較慢）")
            return True
        if n >= 3 or time.time() >= deadline:
            return False
        rd.step("還沒看到進隊，等一下再看")
        rd.nap(2.0)


# ---------------------------------------------------------------------------
# 巡一隻小號
# ---------------------------------------------------------------------------

def visit(idx, hwnd, state, slots_free):
    """處理一隻小號。回傳 (新狀態, 訊息, 這次有沒有佔用一個空位)。"""
    orig = rd.remember_place(hwnd)
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
            rd.restore_place(hwnd, orig)
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


# ===========================================================================
# 燃料輪替
# ===========================================================================
# 鐵匠打怪會掉燃料，每隻角色每天上限 2000。弱的角色進打手的隊伍「跟隨」吸燃料：
#   每個帳號依序：第 2 隻 → 第 3 隻（小號，燃料 2000 就離隊）→ 第 1 隻（本尊，戰鬥次數 10000 才離隊）
#   隊伍 6 人含打手，同時最多 FUEL_MAX 隻在吸；有空位優先給小號（小號約 10 分鐘就滿，本尊要很久）。
# 判斷：對話框「系統」頁
#   有新訊息、有「獲得燃料」→ 還在吸；有新訊息、沒有燃料 → 可能滿了 → 包包確認 2000/2000；
#   連續兩次一模一樣（沒有新訊息）→ 出狀況 → 確認還在隊裡、有在跟隨。
# 腳印是開關：有紅色斜線 = 已跟隨，這時再按會「取消跟隨」，所以一定先看是哪一種才按。

F_WAIT, F_IN, F_DONE, F_ERR = "等空位", "吸燃料中", "完成", "異常"
FUEL_TEMPLATES = ["settings_game.png", "back_login.png", "title_start.png", "charsel_start.png", "leader_star.png",
                  "follow_off.png", "follow_on.png", "chat_sys_tab.png", "chat_fuel.png", "chat_close.png",
                  "fuel_item.png", "fuel_full.png", "friend_close.png",
                  "leave_party.png", "create_party.png", "count_full.png"]


def _fuel_key(hwnd):
    return "fuel|" + rd.account_key(hwnd)


def _region(img, x0, y0, x1, y1):
    h, w = img.shape[:2]
    return img[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]


def _same(a, b, tol=3.0):
    """兩張（同一塊）畫面幾乎一樣嗎。"""
    import cv2
    import numpy as np
    if a is None or b is None or a.shape != b.shape:
        return False
    d = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    return float(np.mean(d)) < tol


def press_until_moved(tmpl, label, moved, timeout=60.0, first_wait=1.5, gap=3.0):
    """點 tmpl 那顆按鈕，直到畫面換掉（moved(畫面) 為真）。

    使用者實測：標題畫面一出現「開始遊戲」就點，常常沒反應（遊戲還要 1～2 秒才準備好），
    以前只點一下就乾等 60 秒 → 卡住。現在：先等 first_wait 秒再點；之後每 gap 秒看一次，
    畫面換了就成功；還看得到同一顆按鈕 = 剛剛沒反應，再點一次。只有真的沒反應才補點，
    不會多點到下一個畫面去。回傳 True 畫面換了 / False 超過 timeout。
    """
    rd.nap(first_wait)
    box = find_one(grab(), tmpl)
    if box:
        click_box(box, wait=0.5)
    n, last = 1, time.time()
    deadline = time.time() + timeout * max(0.5, rd.SLOW)
    while time.time() < deadline:
        screen = grab()
        if moved(screen):
            if n > 1:
                rd.step(f"{label}點了 {n} 次才有反應")
            return True
        if time.time() - last >= gap:
            box = find_one(screen, tmpl)
            if box:
                n += 1
                rd.step(f"{label}沒反應，再點第 {n} 次")
                click_box(box, wait=0.5)
                last = time.time()
        time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# 萬物石換材料（防禦手套）：升級（用萬物之石）→ 交易所上架 → 移除升級狀態拿回材料 → 煤炭鋼鐵存倉庫（2026.11.25）
# ---------------------------------------------------------------------------

WAN_TEMPLATES = ["wan_glove.png", "wan_enhance.png", "wan_stone_on.png", "wan_upgrade_btn.png", "wan_upgraded.png",
                 "wan_glove_up.png", "wan_list_up.png", "wan_list_btn.png", "wan_remove.png",
                 "wan_npc.png", "wan_storage_btn.png", "wan_storage_title.png", "wan_coal.png", "wan_steel.png",
                 "exchange_sell_tab.png"]
WAN_POINTS = ["wan_upgrade_tab", "wan_stone_box", "wan_shared_tab"]
_WAN_EX_KEY = ""                 # 萬物石開交易所按的鍵（萬物石分頁設定，預設 1；空白＝點快捷列）


WAN_MOVE_TIME = 0.25             # 萬物石：滑鼠滑到按鈕花幾秒（以前 0.1 秒，像瞬移）
WAN_HOVER = 0.12                 # 萬物石：移到按鈕上先停幾秒再點（有些介面要先停在上面才收點擊）


class _HoverMoves:
    """萬物石跑的時候，滑鼠慢一點滑過去、停一下再點（使用者：滑鼠像瞬移太快；先只改萬物石，2026.11.25k）。
    程式的點擊都是先 pyautogui.moveTo 再 click，所以只要換掉 moveTo；結束（含中止、出錯）換回來。"""

    def __enter__(self):
        self.orig = pyautogui.moveTo

        def move(*a, **k):
            k["duration"] = max(WAN_MOVE_TIME, float(k.get("duration") or 0))
            r = self.orig(*a, **k)
            time.sleep(WAN_HOVER)
            return r
        pyautogui.moveTo = move
        return self

    def __exit__(self, *exc):
        pyautogui.moveTo = self.orig
        return False


class WanStop(Exception):
    """萬物石流程要整個停下來（訊息給使用者看）。"""


def _wan_point(key):
    v = rd._read_json(rd.CONFIG_PATH).get(key)
    return tuple(v) if v else None


def _dismiss_popups():
    """關掉突然跳出來的邀請視窗（協助邀請之類），只按右上角 ✕，絕對不按「確認」（會傳送走）。
    使用者實測：協助邀請蓋住交易所清單，找不到防禦手套就停了。圖（popup_close.png，含一點右上圓角）是從他的截圖裁的：
    那張 1.00、他其他 40 張遊戲截圖最多 0.69，不會誤認（2026.11.26g）。回傳有沒有關掉東西。"""
    if not has("popup_close.png"):
        return False
    closed = False
    for _ in range(3):
        b = find_one(grab(), "popup_close.png")
        if not b:
            break
        rd.step(f"畫面突然跳出邀請視窗，按右上角 ✕ 關掉（{b[4]:.2f} 分）")
        click_box(b, wait=1.0)
        closed = True
    return closed


def _wan_need(tmpl, timeout, what, seen=None):
    """等某張圖出現：看到就寫「seen（幾分）」；沒出現就停，寫「最像幾分」＋存截圖。
    分數很低＝畫面根本沒出現；0.6～0.8＝畫面有但圖比不到，要重抓那張（使用者要每一步都寫清楚好 debug）。"""
    box = wait_for(tmpl, timeout=timeout)
    if not box and _dismiss_popups():                # 被突然跳出的視窗擋住：關掉再找一次
        box = wait_for(tmpl, timeout=max(2.0, timeout))
    if not box:
        near = find_one(grab(), tmpl, threshold=0.3)
        sc = near[4] if near else 0.0
        hint = "（畫面有但圖比不到，建議重抓這張）" if sc >= 0.6 else ""
        raise WanStop(f"{what}（{tmpl} 最像 {sc:.2f} 分，要 {rd.MATCH_THRESHOLD:g}）{hint}"
                      f"（{dump_fail('wan_' + tmpl[4:-4])}）")
    if seen:
        rd.step(f"{seen}（{box[4]:.2f} 分）")
    return box


def _wan_dclick(box):
    """點兩下（煤炭、鋼鐵在倉庫畫面要點兩下才會存進去）。"""
    cx, cy = box[0] + box[2] // 2, box[1] + box[3] // 2
    pyautogui.moveTo(rd.AREA_X + cx, rd.AREA_Y + cy, duration=0.1)
    pyautogui.click(clicks=2, interval=0.15)
    rd.nap(1.2)


def _wan_right(tmpl):
    """倉庫畫面右半邊（包包那邊）的這張圖；左邊倉庫裡也有煤炭鋼鐵，不能點到那邊。"""
    for b in rd.find_all(grab(), tmpl):
        if b[0] + b[2] // 2 > rd.AREA_W * 0.5:
            return b
    return None


def _wan_scroll_find(tmpl, name):
    """包包第一頁沒看到就往下捲來找（使用者：手套不在第一頁，2026.11.25g）。
    只往下捲：點「裝備」分頁時清單就會回到最上面（使用者說的，2026.11.25h）。邊捲邊找，拖不動＝到底。
    拖曳起點用萬物石自己的 wan_bag_scroll，沒抓就借燃料輪替的 bag_scroll。"""
    if find_one(grab(), tmpl):
        return True
    pt = _wan_point("wan_bag_scroll") or (tuple(P_BAG_SCROLL) if P_BAG_SCROLL else None)
    if not pt:
        rd.step(f"第一頁沒看到{name}，但還沒校正「包包格子區的正中間」，沒辦法往下捲")
        return False
    x, y = pt
    d = int(rd.AREA_W * 150 / 800)
    rd.step(f"第一頁沒看到{name}，往下捲來找")
    for i in range(1, 13):                             # 往上拖＝清單往下捲
        before = grab()
        rd.drag_line(x, y, x, y - d, steps=16, hold=0.03)
        rd.nap(0.6)
        after = grab()
        hit = find_one(after, tmpl)
        if hit:
            rd.step(f"往下捲第 {i} 次：找到{name}（{hit[4]:.2f} 分）")
            return True
        if not _area_changed(before, after, x, y, d):
            rd.step(f"往下捲第 {i} 次：拖不動了（到底了）")
            break
    return False


def _wan_pick_plain_glove():
    """包包裡可能同時有「沒升級的那疊」和「升級過的」（上一輪中途停下來時）。每個候選都比一下像不像升級過的，
    挑最不像升級過的那個（使用者截圖：21 雙疊在一格；2026.11.25c）。"""
    screen = grab()
    cands = rd.find_all(screen, "wan_glove.png")
    if len(cands) <= 1:
        g = cands[0] if cands else find_one(screen, "wan_glove.png")
        rd.step(f"找到防禦手套，點它（{g[4]:.2f} 分）")
        return g
    h, w = screen.shape[:2]
    best, best_up = None, 9.0
    for c in cands:
        x0, y0 = max(0, c[0] - 12), max(0, c[1] - 12)
        x1, y1 = min(w, c[0] + c[2] + 12), min(h, c[1] + c[3] + 12)
        up = find_one(screen[y0:y1, x0:x1], "wan_glove_up.png", threshold=0.3)
        sc = up[4] if up else 0.0
        if sc < best_up:
            best, best_up = c, sc
    rd.step(f"包包裡有 {len(cands)} 個防禦手套，挑沒升級的那個（像升級過的只有 {best_up:.2f} 分），點它")
    return best


def _ink(region):
    """數「筆畫」點：比這一塊的背景（中位數）暗 40 以上、而且是灰黑色（不是彩色外框）。
    以前用固定「亮度 <140」：遊戲實際大小（800 寬）下 I 只有一兩點、顏色淡，會數到 0（使用者實測「要 0 以上」，2026.11.25i）。"""
    if region is None or not region.size:
        return 0
    r = region.astype("int16")
    g = r.mean(axis=2)
    sat = r.max(axis=2) - r.min(axis=2)
    import numpy as np
    return int(((g < np.median(g) - 40) & (sat < 45)).sum())


def _tmpl_of(box, fallback):
    try:
        return rd.load_template(box[5])
    except Exception:
        return rd.load_template(fallback)


def _col_ink(region):
    """每一欄有幾個「明顯的筆畫點」：比這一塊最亮的背景（第 90 百分位）暗 70 以上、而且是灰黑色。
    用最亮背景當基準：框裡留白多寡不影響（用中位數的話，留白多會把字邊緣的淡灰也算進去，「套」和 I 中間的空隙就被填掉）。"""
    import numpy as np
    r = region.astype("int16")
    g = r.mean(axis=2)
    sat = r.max(axis=2) - r.min(axis=2)
    m = (g < np.percentile(g, 90) - 70) & (sat < 45)
    return m.sum(axis=0), m


def _i_segment(tmpl):
    """從「套I」那張圖自己找出 I 在哪幾欄：最右邊一段筆畫，前面隔至少一欄空白（跟「套」分開）、
    很細（≤ 寬 15%）、在右半邊、夠高（≥ 圖高 35%）。找不到＝圖沒框到 I。回傳 (起, 迄, 筆畫點) 或 None。"""
    import numpy as np
    cols, m = _col_ink(tmpl)
    w, h = len(cols), tmpl.shape[0]
    segs, x = [], 0
    while x < w:
        if cols[x] > 0:
            st = x
            while x < w and cols[x] > 0:
                x += 1
            segs.append((st, x - 1))
        else:
            x += 1
    if len(segs) < 2:
        return None
    st, en = segs[-1]
    gap = st - segs[-2][1] - 1
    rows = np.where(m[:, st:en + 1].any(axis=1))[0]
    tall = (rows.max() - rows.min() + 1) if len(rows) else 0
    text_rows = np.where(m[:, :st].any(axis=1))[0]            # 左邊「套」字的高度
    text_h = (text_rows.max() - text_rows.min() + 1) if len(text_rows) else h
    # I 的高度跟「字」比，不跟整張圖比：使用者框高 24、上下留白多，I 只有 8 格（套 15 格）→ 跟圖比會誤判找不到（2026.11.25m）
    if gap >= 1 and (en - st + 1) <= max(2, int(w * 0.15)) and st >= w * 0.55 and tall >= text_h * 0.35:
        return st, en, int(cols[st:en + 1].sum())
    return None


def _wan_has_I(screen, box):
    """上架視窗標題「套I」：從模板找出 I 在哪幾欄，只看遊戲畫面那幾欄有沒有筆畫（要有模板的一半以上）。
    用使用者真實截圖測六種框法（I 貼邊／右邊留白／留很多白／框整串）：有 I 都通過、把 I 擦掉都是 0 點；
    沒框到 I、只框半個套 → 找不到 I，叫他重抓（2026.11.25l）。
    回傳 (是不是, 這次的點, 模板的點)；模板的點是 0 代表那張圖沒框到 I。"""
    import cv2
    tmpl = _tmpl_of(box, "wan_list_up.png")
    seg = _i_segment(tmpl)
    if not seg:
        return False, 0, 0
    st, en, T = seg
    x, y, w, h = box[0], box[1], box[2], box[3]
    region = screen[y:y + h, x:x + w]
    if region.shape[:2] != tmpl.shape[:2]:
        region = cv2.resize(region, (tmpl.shape[1], tmpl.shape[0]), interpolation=cv2.INTER_AREA)
    cols, _ = _col_ink(region)
    S = int(cols[st:en + 2].sum())                 # 右邊多看一欄（比對位置差一點也沒關係）
    return S >= 0.5 * T, S, T


def _icon_spot(img):
    """手套格子右上角放「I」的那一小塊（實測 I 在格子寬 82～96%、高 6～32% 的位置）。"""
    h, w = img.shape[:2]
    return img[int(h * 0.05):int(h * 0.34), int(w * 0.80):int(w * 0.97)]


def _wan_icon_has_I(screen, box):
    """交易所清單裡這格手套右上角有沒有升級的「I」。實測：升級過 10～30 點、沒升級那疊 0 點。
    回傳 True／False，模板右上角沒框到 I（看不出來）回傳 None。"""
    tmpl = _tmpl_of(box, "wan_glove_up.png")
    T = _ink(_icon_spot(tmpl))
    if T == 0:
        return None
    S = _ink(_icon_spot(screen[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]))
    S = int(round(S * tmpl.shape[0] * tmpl.shape[1] / max(1, box[2] * box[3])))
    return S >= 0.5 * T


def _wan_upgrade():
    """包包 → 裝備分頁 → 防禦手套 → 強化 → 升級 → 勾萬物之石 → 升級 → 確認變成「防禦手套I」。"""
    if not on_main():
        back_to_main()
    if rd.HOTKEYS:
        rd.step(f"打開包包（按 {BAG_KEY.upper()}）")
        pyautogui.press(BAG_KEY)
        rd.nap(0.8)
    elif P_BAG_BTN:
        rd.step("打開包包（點包包按鈕）")
        click_at(P_BAG_BTN[0], P_BAG_BTN[1], wait=rd.T_PANEL_MAX)
    wait_stable(1.5)
    # 包包打開就是 All 分頁；手套存進倉庫再拿出來會排在第一排（使用者說的）。不點「裝備」分頁：點了反而看不到（2026.11.25j）
    rd.step("在包包 All 第一頁找防禦手套")
    if not wait_for("wan_glove.png", timeout=3.0) and not _wan_scroll_find("wan_glove.png", "防禦手套"):
        _wan_need("wan_glove.png", 0.5, "包包裡找不到防禦手套（已經捲到底了；手套存進倉庫再拿出來會排在第一排）")
    g = _wan_pick_plain_glove()
    click_box(g, wait=1.0)
    e = _wan_need("wan_enhance.png", 4.0, "點了手套但沒看到「強化」按鈕", "看到「強化」，點它")
    click_box(e, wait=rd.T_PANEL_MAX)
    up = _wan_point("wan_upgrade_tab")
    rd.step("點左邊的「升級」")
    click_at(up[0], up[1], wait=1.5)
    on = wait_for("wan_stone_on.png", timeout=2.0)
    if not on:
        box = _wan_point("wan_stone_box")
        rd.step("「使用萬物之石」還沒勾，勾起來")
        click_at(box[0], box[1], wait=1.0)
        _wan_need("wan_stone_on.png", 3.0, "勾了「使用萬物之石」但沒看到打勾", "看到已經打勾")
    else:
        rd.step(f"「使用萬物之石」已經勾著（{on[4]:.2f} 分）")
    # 沒勾的時候按鈕是「購買材料」，只認得「升級」這張圖，不會按到購買材料
    b = _wan_need("wan_upgrade_btn.png", 3.0, "沒看到黃色「升級」按鈕（萬物之石沒勾到、或萬物石不夠變成購買材料？）",
                  "看到「升級」，按下去")
    click_box(b, wait=1.5)
    _wan_need("wan_upgraded.png", 6.0, "按了升級，但沒看到手套變成「防禦手套I」（萬物石或 Zeny 不夠？）",
              "手套升到 I 了")
    rd.step("關掉強化畫面")
    back_to_main()


def _wan_remove():
    """交易所 → 我要出售 → 點「防禦手套I」→ 確認是升級過的 → 上架 → 一定要看到「移除」才按，拿回材料。"""
    if not on_main():
        back_to_main()
    def open_ex():
        if _WAN_EX_KEY:
            rd.press_keys(_WAN_EX_KEY, "開交易所")       # 萬物石分頁設定的鍵（預設 1）
        elif rd.EXCHANGE_SLOT:
            rd.step("點快捷列的交易所")
            click_at(rd.EXCHANGE_SLOT[0], rd.EXCHANGE_SLOT[1], wait=rd.T_PANEL_MAX)
        else:
            raise WanStop("開交易所的鍵沒填、快捷列交易所的位置也還沒校正（校正頁「一鍵上架」那組）")
    open_ex()
    tab = wait_for("exchange_sell_tab.png", timeout=4.0)
    if not tab and on_main():
        rd.step("交易所沒反應，再試一次")
        open_ex()
    tab = tab or _wan_need("exchange_sell_tab.png", 8.0, "打不開交易所")
    rd.step(f"交易所打開了，點「我要出售」（{tab[4]:.2f} 分）")
    click_box(tab, wait=rd.T_PANEL_MAX)
    _wan_need("wan_glove_up.png", 4.0, "我要出售的清單裡找不到升級過的防禦手套")
    # 點之前確認這格右上角有「I」：包包有一疊沒升級的時候，「升級過」那張圖也會比到那疊（使用者實測 0.82 分點錯）
    sc = grab()
    cands = rd.find_all(sc, "wan_glove_up.png")
    marks = [(c, _wan_icon_has_I(sc, c)) for c in cands]
    good = [c for c, m in marks if m]
    if good:
        g = good[0]
        rd.step(f"找到右上角有 I 的「防禦手套I」，點它（{g[4]:.2f} 分）")
    elif all(m is None for _, m in marks):
        g = cands[0]
        rd.step(f"找到「防禦手套I」，點它（{g[4]:.2f} 分；⚠ 這張圖右上角沒框到 I，沒辦法先確認，靠上架視窗的「套I」把關，建議重抓）")
    else:
        shot = dump_fail("wan_no_I_icon")
        back_to_main()
        raise WanStop("交易所清單看得到的防禦手套，右上角都沒有「I」（點到的會是沒升級的那疊），所以不點。"
                      f"建議包包只留 1 雙手套，其他放倉庫（{shot}）")
    click_box(g, wait=1.5)
    # 保險一：上架視窗一定要是「防禦手套I」（升級過的）才按上架，不然會真的把手套賣掉
    # 只框「套I」兩個字、門檻 0.9：沒有 I 的話那一塊是空白，分數一定很低（使用者截圖有 21 雙沒升級的疊在旁邊，
    # 萬一點錯，「防禦手套」跟「防禦手套I」只差一個 I，框整串的話保險可能擋不住；2026.11.25c）
    lu, ok_i, S, T = None, False, 0, 0
    deadline = time.time() + 4.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        sc = grab()
        lu = find_one(sc, "wan_list_up.png", threshold=0.85)
        if lu:
            ok_i, S, T = _wan_has_I(sc, lu)
            if ok_i:
                break
        time.sleep(0.4)
    if lu and not ok_i:
        shot = dump_fail("wan_list_no_I")
        back_to_main()
        if T == 0:
            raise WanStop("「套I」那張圖的 I 那一塊沒有筆畫（沒框到 I），沒辦法確認是不是升級過的，所以沒有按上架。"
                          f"請到校正頁重抓「套I」，框到 I、右邊不要留太多空白（{shot}）")
        raise WanStop(f"上架視窗標題後面沒有「I」（I 那一塊筆畫 {S}，要 {0.75 * T:.0f} 以上），"
                      f"這隻手套沒升級，為了不把手套賣掉，沒有按上架（{shot}）")
    if not lu:
        near = find_one(grab(), "wan_list_up.png", threshold=0.3)
        shot = dump_fail("wan_list_not_up")
        back_to_main()
        raise WanStop(f"上架視窗不是「防禦手套I」（「套I」最像 {near[4] if near else 0.0:.2f} 分，要 0.9），"
                      f"為了不把手套賣掉，沒有按上架（{shot}）")
    rd.step(f"確認上架視窗是「防禦手套I」（{lu[4]:.2f} 分；I 那一塊筆畫 {S}／{T}）")
    lb = _wan_need("wan_list_btn.png", 3.0, "上架視窗裡找不到「上架」按鈕", "看到「上架」，按下去")
    click_box(lb, wait=1.0)
    # 有時候先跳「注意：價格會隨市場浮動」（不再提示／取消上架／繼續上架）。上面已經確認是「防禦手套I」，
    # 升級過的遊戲不讓上架，按「繼續上架」一定會跳「移除」，所以可以按（使用者截圖，2026.11.25d）
    rm = notice = None
    deadline = time.time() + 6.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        sc = grab()
        rm = find_one(sc, "wan_remove.png")
        if rm:
            break
        if has("wan_notice_go.png"):
            notice = find_one(sc, "wan_notice_go.png")
            if notice:
                break
        time.sleep(0.4)
    if notice and not rm:
        rd.step(f"跳出「注意：價格會浮動」視窗（{notice[4]:.2f} 分）")
        cb = find_one(grab(), "wan_notice_check.png") if has("wan_notice_check.png") else None
        if cb:
            rd.step(f"勾「不再提示」（{cb[4]:.2f} 分）")
            click_at(cb[0] + max(6, cb[3] // 2), cb[1] + cb[3] // 2, wait=0.8)   # 勾選框在最左邊
        rd.step("按「繼續上架」（已確認是防禦手套I，遊戲一定會跳「移除」）")
        click_box(notice, wait=1.5)
        rm = wait_for("wan_remove.png", timeout=6.0)
    # 保險二：一定要跳出「移除升級狀態」才是對的；沒有就可能真的上架了，整個停下來
    if not rm:
        shot = dump_fail("wan_no_remove")
        raise WanStop("⚠⚠ 按了「上架」但沒看到「移除升級狀態」視窗！手套可能真的上架了，"
                      "請馬上到交易所「正在出售」檢查，有的話下架。"
                      "（如果畫面停在「注意：價格會浮動」視窗，代表還沒上架：按「取消上架」，"
                      f"再到校正頁抓「繼續上架」和「不再提示」那兩張）（{shot}）")
    rd.step(f"跳出「移除升級狀態」，按「移除」（{rm[4]:.2f} 分；5000 Zeny，拿回煤炭、鋼鐵）")
    click_box(rm, wait=2.0)
    if wait_until(lambda sc: find_one(sc, "wan_remove.png") is not None, 2.0):
        rd.step("「移除」還在，再按一次")
        click_box(rm, wait=2.0)
    wait_stable(2.0)
    rd.step("關掉交易所")
    back_to_main()


def _find_scaled(screen, tmpl, lo=0.75, hi=1.4):
    """用好幾種大小比（卡普拉頭上的對話框會隨角色站遠站近、鏡頭距離變大變小）。
    使用者實測：原大小只有 0.69 分；用 0.9～1.15 倍都到 0.86～0.95；遮掉真的對話框後別處最多 0.65 分，不會認錯（2026.11.26b）。
    先在縮小一半的畫面粗找（每 0.1 倍一種），再回原大小在找到的附近細找（±0.05 倍），比一張一張全畫面比快很多。
    回傳 (最好的框或 None, 最好分數)；框的格式跟 find_one 一樣。"""
    import cv2
    import numpy as np
    small = cv2.resize(screen, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = []                                       # (分數, 圖, 倍數, x, y)
    for v in rd.template_variants(tmpl):
        try:
            t = rd.load_template(v)
        except Exception:
            continue
        for k in np.arange(lo, hi + 1e-6, 0.1):
            tt = cv2.resize(t, None, fx=k * 0.5, fy=k * 0.5, interpolation=cv2.INTER_AREA)
            if tt.shape[0] < 6 or tt.shape[1] < 6 or tt.shape[0] > small.shape[0] or tt.shape[1] > small.shape[1]:
                continue
            r = cv2.matchTemplate(small, tt, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            coarse.append((float(mx), v, float(k), loc[0] * 2, loc[1] * 2))
    coarse.sort(reverse=True)
    best, best_box = 0.0, None
    H, W = screen.shape[:2]
    for _, v, k0, x0, y0 in coarse[:3]:               # 最像的前三個，回原大小在附近細找
        t = rd.load_template(v)
        for k in np.arange(k0 - 0.05, k0 + 0.051, 0.025):
            tt = cv2.resize(t, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
            th, tw = tt.shape[:2]
            ax, ay = max(0, x0 - 16), max(0, y0 - 16)
            bx, by = min(W, x0 + tw + 16), min(H, y0 + th + 16)
            if bx - ax < tw or by - ay < th:
                continue
            r = cv2.matchTemplate(screen[ay:by, ax:bx], tt, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if mx > best:
                best, best_box = float(mx), (ax + loc[0], ay + loc[1], tw, th, float(mx), v)
    return (best_box if best >= rd.MATCH_THRESHOLD else None), best


def _wan_stable(tmpl, timeout, what, scaled=False):
    """找到按鈕後，連看兩次位置都一樣（差 3 點以內）才回傳；還在動就等。
    使用者實測：點「倉庫服務」時角色位移、點到地板——點卡普拉後角色走過去，鏡頭跟著動，選單也在動，
    找到時的位置跟滑鼠到的時候不一樣（2026.11.25p）。"""
    deadline = time.time() + timeout * max(0.5, rd.SLOW)
    told = False
    find = (lambda sc: _find_scaled(sc, tmpl)[0]) if scaled else (lambda sc: find_one(sc, tmpl))
    while time.time() < deadline:
        b1 = find(grab())
        if not b1:
            time.sleep(0.3)
            continue
        time.sleep(0.35)
        b2 = find(grab())
        if b2 and abs(b2[0] - b1[0]) <= 3 and abs(b2[1] - b1[1]) <= 3:
            return b2
        if not told:
            rd.step(f"{what}還在移動（角色在走），等它停下來再點")
            told = True
    return None


def _wan_debug_click(box, name):
    """點之前存一張圖，在要點的位置畫紅圈（shots\\debug_名字.png，每次覆蓋）。使用者說點到地板但很難描述 → 直接看圖（2026.11.26c）。"""
    try:
        import cv2
        x, y, w, h = box[0], box[1], box[2], box[3]
        off = rd.CLICK_OFFSET.get(box[5])
        cx, cy = (x + off[0], y + off[1]) if off else (x + w // 2, y + h // 2)
        img = grab().copy()
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 255), 1)
        cv2.circle(img, (cx, cy), 9, (0, 0, 255), 2)
        cv2.circle(img, (cx, cy), 2, (0, 0, 255), -1)
        os.makedirs(rd.SHOT_DIR, exist_ok=True)
        path = os.path.join(rd.SHOT_DIR, f"debug_{name}.png")
        rd.imwrite(path, img)
        rd.step(f"（要點在 ({cx}, {cy})，存了標記圖：{path}）")
    except Exception as e:
        rd.step(f"（存標記圖失敗：{e}）")


def _wan_deposit():
    """點卡普拉頭上的對話框 → 倉庫服務 → 右邊包包的煤炭、鋼鐵各點兩下存進倉庫。"""
    if not on_main():
        back_to_main()
    # 卡普拉偶爾會講話，對話泡泡會蓋住「倉庫/儲存/傳送」幾秒（使用者截圖）→ 最多等 10 秒（2026.11.25f）
    # 對話框會隨角色站遠站近變大變小 → 用好幾種大小比，再確認位置停住了才點（2026.11.26b）
    n = _wan_stable("wan_npc.png", 2.0, "卡普拉頭上的對話框", scaled=True)
    if not n:
        _dismiss_popups()
        rd.step("還沒看到卡普拉頭上的對話框（可能被 NPC 講話的泡泡擋住），最多再等 8 秒")
        n = _wan_stable("wan_npc.png", 8.0, "卡普拉頭上的對話框", scaled=True)
    if not n:
        _, sc = _find_scaled(grab(), "wan_npc.png")
        raise WanStop("等了 10 秒都找不到卡普拉頭上的「倉庫/儲存/傳送」對話框（角色要站在卡普拉旁邊）"
                      f"（用好幾種大小比，最像 {sc:.2f} 分，要 {rd.MATCH_THRESHOLD:g}）（{dump_fail('wan_npc')}）")
    rd.step(f"看到卡普拉頭上的對話框，點它（{n[4]:.2f} 分）")
    click_box(n, wait=1.5)
    # 點了對話框後角色要先走到卡普拉旁邊，選單才會跳出來 → 等 8 秒（以前 4 秒，使用者截圖選單還沒出來就停了）
    _wan_need("wan_storage_btn.png", 8.0, "點了卡普拉對話框，等了 8 秒沒看到「倉庫服務」（角色離卡普拉太遠？）")
    sb = _wan_stable("wan_storage_btn.png", 6.0, "「倉庫服務」")
    if not sb:
        raise WanStop(f"「倉庫服務」一直在移動、停不下來，沒有點（避免點到地板讓角色走掉）（{dump_fail('wan_storage_moving')}）")
    # 選單跳出來有淡入動畫，淡入中按下去會「穿過去」點到後面的地板（使用者：還是點到右邊地板）。
    # 停好後再等 1 秒，而且要 0.9 分以上（淡入中比較透明、分數比較低）才點；4 秒都不到 0.9 就用 0.8 以上的照點（2026.11.26c）
    rd.step("「倉庫服務」停好了，再等 1 秒讓選單動畫跑完")
    rd.nap(1.0)
    sure = None
    deadline = time.time() + 4.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        sure = find_one(grab(), "wan_storage_btn.png", threshold=0.9)
        if sure:
            break
        time.sleep(0.3)
    if sure:
        sb = sure
    else:
        sb = find_one(grab(), "wan_storage_btn.png") or sb
        rd.step(f"「倉庫服務」一直沒到 0.9 分（{sb[4]:.2f}），照樣點")
    _wan_debug_click(sb, "倉庫服務")
    rd.step(f"點「倉庫服務」（{sb[4]:.2f} 分）")
    click_box(sb, wait=rd.T_PANEL_MAX)
    _wan_need("wan_storage_title.png", 6.0, "倉庫沒打開", "倉庫打開了")
    # 要存進「通用倉庫」（使用者提醒）；已經在那一頁的話再點一次也沒關係
    sh = _wan_point("wan_shared_tab")
    rd.step("點左邊的「通用倉庫」分頁")
    click_at(sh[0], sh[1], wait=1.5)
    wait_stable(1.5)
    for tmpl, name in (("wan_coal.png", "煤炭"), ("wan_steel.png", "鋼鐵")):
        b = _wan_right(tmpl)
        if not b:
            # 每輪「移除升級」一定會拿回煤炭和鋼鐵，所以這裡一定有；找不到＝圖比不到。
            # 以前寫「可能已經存過了，跳過」→ 使用者跑了 20 輪鋼鐵都沒存（下一輪升級改吃包包裡的鋼鐵，沒用到萬物石），2026.11.26d
            sc = grab()
            w = sc.shape[1]
            near = None
            for c in rd.find_all(sc, tmpl, threshold=0.3):
                if c[0] + c[2] // 2 > w * 0.5:
                    near = c
                    break
            score = near[4] if near else 0.0
            shot = dump_fail(f"wan_{tmpl[4:-4]}")
            back_to_main()
            raise WanStop(f"倉庫畫面右邊包包裡找不到{name}（最像 {score:.2f} 分，要 {rd.MATCH_THRESHOLD:g}）。"
                          f"剛拿回來的{name}左上角會有紅色「New」，抓圖時請框圖示的中間偏下，避開左上角和右下角的數字，"
                          f"在跑的時候（有 New 的狀態）重抓「倉庫畫面右邊包包裡的{name}」（{shot}）")
        for k in range(1, 4):
            rd.step(f"{name}點兩下存進倉庫（{b[4]:.2f} 分）" + (f"（第 {k} 次）" if k > 1 else ""))
            _wan_dclick(b)
            b = _wan_right(tmpl)
            if not b:
                break
        else:
            shot = dump_fail("wan_deposit")
            back_to_main()
            raise WanStop(f"{name}點了 3 次還在包包裡，存不進倉庫（下一輪升級會用到包包裡的材料，先停下來；{shot}）")
    rd.step("煤炭、鋼鐵都存進倉庫了，關掉倉庫")
    back_to_main()


def wan_run(hwnd, rounds, ex_key="1"):
    """萬物石換材料跑 rounds 輪。任何一步不對就整個停下來（存截圖、寫原因）。ex_key：開交易所按的鍵，空白＝點快捷列。"""
    global _WAN_EX_KEY
    _WAN_EX_KEY = (ex_key or "").strip()
    home = rd.ACTIVE_PROFILE
    rd.STEP_TIME = True
    done = 0
    try:
        kind = rd.kind_of(hwnd)
        rd.use_profile(kind)
        _load()
        lack = [t for t in WAN_TEMPLATES if not has(t)] + [p for p in WAN_POINTS if not _wan_point(p)]
        if lack:
            print(f"【{kind}】萬物石還沒校正完：" + "、".join(lack) + "（校正頁「萬物石（防禦手套）」那組；交易所在「一鍵上架」那組）")
            return
        label = rd.window_label(hwnd)
        print(f"萬物石換材料：{label}，跑 {rounds} 輪（每輪約 5000 Zeny＋8 顆萬物石，換煤炭 80、鋼鐵 80）；"
              f"開交易所：{('按 ' + _WAN_EX_KEY.upper()) if _WAN_EX_KEY else '點快捷列第 1 格'}")
        orig = rd.remember_place(hwnd)
        hover = _HoverMoves().__enter__()
        try:
            _use(hwnd)
            rd.normalize_window(hwnd)
            t0 = time.time()
            for n in range(1, rounds + 1):
                print(f"\n──── {time.strftime('%H:%M:%S')}　第 {n}/{rounds} 輪 ────", flush=True)
                for what, fn in (("升級", _wan_upgrade), ("移除升級", _wan_remove), ("存倉庫", _wan_deposit)):
                    rd.step(f"【{what}】")
                    try:
                        fn()
                    except WanStop as e:
                        print(f"\n✗ 第 {n} 輪在「{what}」停下來：{e}")
                        print(f"完成 {done} 輪，共 {(time.time() - t0) / 60:.0f} 分鐘。")
                        return
                    except rd.Aborted:
                        print(f"\n已停止（按了停止／F12），第 {n} 輪做到「{what}」。完成 {done} 輪，共 {(time.time() - t0) / 60:.0f} 分鐘。")
                        return
                done += 1
                print(f"  {time.strftime('%H:%M:%S')} → 第 {n} 輪完成", flush=True)
            print(f"\n✓ {rounds} 輪全部完成，共 {(time.time() - t0) / 60:.0f} 分鐘。")
        finally:
            hover.__exit__(None, None, None)
            try:
                rd.restore_place(hwnd, orig)
            except Exception:
                pass
    finally:
        rd.STEP_TIME = False
        rd.use_profile(home)
        _load()


# ---------------------------------------------------------------------------
# 開帳號：用帳號切換的備份，一個一個開官方遊戲並進到遊戲（2026.11.23）
# ---------------------------------------------------------------------------

def _acct_mod():
    """把旁邊的 account_switch.pyw 當成模組載入（用它的換帳號功能，不用另外打開帳號切換）。"""
    import importlib.machinery
    import importlib.util
    path = os.path.join(rd.BASE_DIR, "account_switch.pyw")
    loader = importlib.machinery.SourceFileLoader("account_switch_mod", path)
    spec = importlib.util.spec_from_loader("account_switch_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


OPEN_TEMPLATES = ["title_start.png", "charsel_start.png"]


def open_accounts(plan, cols=0):
    """plan = [(帳號名, 資料夾完整路徑, exe)]。每個帳號：放回登入資料 → 開那個資料夾的遊戲 →
    等視窗 → 標題「開始遊戲」→ 選本尊 → 進遊戲，**完全進到遊戲才換下一個**。

    所有官方遊戲共用同一份登入資料（LocalLow），前一個還在登入時就換掉，下一個可能會登成同一隻。"""
    import subprocess
    home = rd.ACTIVE_PROFILE
    rd.STEP_TIME = True
    try:
        acc = _acct_mod()
        root = acc.game_root()
        if not root:
            print("找不到官方遊戲的登入資料位置（這台電腦還沒開過官方遊戲？）")
            return
        rd.use_profile("官方")
        _load()
        lack = [t for t in OPEN_TEMPLATES if not has(t)]
        if lack:
            print("【官方】開帳號需要的模板還沒抓：" + "、".join(lack)
                  + "（校正頁「燃料輪替」那組：標題畫面的「開始遊戲」、選角畫面的「開始遊戲」）")
            return
        print(f"開帳號：{len(plan)} 個，一個完全進到遊戲才換下一個（大約每個 1～3 分鐘）")
        if acc.who_is_current(root) == "":
            acc.save_account(root, acc.AUTO_BACKUP)
            print("  目前的登入還沒記住過，先自動留一份「換帳號前自動留的備份」")
        results = []
        for name, folder, exe in plan:
            fname = os.path.basename(folder)
            print(f"\n──── {time.strftime('%H:%M:%S')}　{name} → {fname} ────", flush=True)
            if any(rd.window_label(h) == fname for h in rd.find_windows()):
                results.append((name, fname, "⚠ 這個資料夾已經開著了，跳過（要開的話先把它關掉）"))
                print(f"  → {results[-1][2]}")
                continue
            rd.step(f"換成「{name}」的登入資料")
            acc.restore_account(root, name)
            if acc.who_is_current(root) != name:
                results.append((name, fname, "✗ 放回登入資料後檢查不是這隻，跳過（到帳號切換重新記住這隻）"))
                print(f"  → {results[-1][2]}")
                continue
            rd.step(f"開 {fname} 的遊戲")
            try:
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
            except Exception as e:
                results.append((name, fname, f"✗ 開不起來：{e}"))
                print(f"  → {results[-1][2]}")
                continue
            hwnd = None
            deadline = time.time() + 90
            while time.time() < deadline and not hwnd:
                if rd.ABORT:
                    raise rd.Aborted()
                time.sleep(2)
                hwnd = next((h for h in rd.find_windows() if rd.window_label(h) == fname), None)
            if not hwnd:
                results.append((name, fname, "✗ 等了 90 秒視窗沒出現（閃退或被擋？）"))
                print(f"  → {results[-1][2]}")
                continue
            rd.step("視窗出現了，搬到左上角，等標題畫面（剛開遊戲可能要 1～3 分鐘）；"
                    f"每 {rd.WATCH_GAP:g} 秒檢查一次，遊戲把視窗移走就拉回來")
            orig = rd.remember_place(hwnd)
            pulls = 0
            try:
                _use(hwnd)
                rd.normalize_window(hwnd)
                rd.watch_window(hwnd)                 # 剛開的遊戲會自己跳回正中間：盯著拉回來
                r = enter_from_title(1, title_timeout=180.0, need_slot=False)
            finally:
                pulls = rd.watch_window(None)
                try:
                    rd.restore_place(hwnd, orig)
                except Exception:
                    pass
            if pulls:
                rd.step(f"這個視窗被遊戲移走、拉回來了 {pulls} 次")
            if r is True:
                results.append((name, fname, "✓ 進到遊戲了"))
            elif r == "empty":
                results.append((name, fname, "⚠ 選角畫面第 1 格是空的"))
            else:
                shot = dump_fail(f"open_{fname}")
                results.append((name, fname, "✗ 沒進到遊戲（如果停在 Google／Apple 登入畫面，是這隻的登入資料過期了："
                                             f"手動登入後到帳號切換重新記住；{shot}）"))
            print(f"  → {results[-1][2]}")
        print("\n========== 開帳號結果 ==========")
        for name, fname, msg in results:
            print(f"  {name}（{fname}）：{msg}")
        if any(m.startswith("✓") or "沒進到遊戲" in m or "第 1 格是空的" in m for _, _, m in results):
            print("\n全部開完，自動排列視窗：", flush=True)
            try:
                rd.arrange_windows(cols=cols, log=print)
            except Exception as e:
                print(f"  自動排列失敗：{e}（可以自己按「自動排列視窗」）")
    finally:
        rd.STEP_TIME = False
        rd.use_profile(home)
        _load()


def switch_character(slot):
    """設置 →「回到登錄」→ 標題「開始遊戲」→ 選第 slot 隻 →「開始遊戲」→ 等回到主畫面。
    回傳 True 成功 / "empty" 這格沒有角色（「＋」）/ False 失敗。"""
    rd.step(f"換到第 {slot} 隻角色：打開設置")
    if not rd.open_settings():
        rd.step("打不開設置")
        return False
    btn = wait_for("back_login.png", timeout=5.0)
    if not btn:
        rd.step("設置裡找不到「回到登錄」")
        return False
    click_box(btn, wait=rd.T_PANEL_MAX)
    ok = find_one(grab(), "confirm_ok.png")          # 有些版本會問要不要確定
    if ok:
        click_box(ok)
    rd.step("按了「回到登錄」，等標題畫面（通常 5～10 秒）")
    return enter_from_title(slot)


def enter_from_title(slot, title_timeout=60.0, need_slot=True):
    """從標題畫面一路進到遊戲：等「開始遊戲」→ 按 → 選角畫面選第 slot 隻 → 按「開始遊戲」→ 等回到主畫面。
    換角色（switch_character）和開帳號（open_accounts）共用。
    need_slot=False：選角頭像位置沒校正時不選，直接進上次玩的那隻。
    回傳 True 成功 / "empty" 這格沒有角色 / False 失敗。"""
    t = wait_for("title_start.png", timeout=title_timeout)
    if not t:
        rd.step("等不到標題畫面的「開始遊戲」")
        return False
    rd.step("看到標題畫面，等一下再按「開始遊戲」")
    if not press_until_moved("title_start.png", "標題畫面的「開始遊戲」",
                             lambda sc: find_one(sc, "charsel_start.png") is not None):
        rd.step("等不到選角畫面")
        return False
    pt = P_CHAR_SLOTS[slot - 1]
    if not pt and need_slot:
        rd.step(f"選角畫面第 {slot} 個頭像的位置還沒校正")
        return False
    if not pt:
        rd.step(f"選角頭像位置沒校正，直接進上次玩的那隻")
    else:
        if has("charsel_plus.png"):
            plus = find_one(grab(), "charsel_plus.png")
            if plus and abs(plus[0] + plus[2] // 2 - pt[0]) < 45 and abs(plus[1] + plus[3] // 2 - pt[1]) < 45:
                rd.step(f"第 {slot} 格是「＋」：這個帳號沒有第 {slot} 隻")
                return "empty"
        rd.step(f"選第 {slot} 隻{'（本尊）' if slot == 1 else ''}")
        click_at(pt[0], pt[1], wait=1.5)
    st = wait_for("charsel_start.png", timeout=5.0)
    if not st:
        return False
    # 選角畫面的「開始遊戲」一樣可能點太快沒反應：離開選角畫面（看不到這顆按鈕）就算按到了
    if not press_until_moved("charsel_start.png", "選角畫面的「開始遊戲」",
                             lambda sc: find_one(sc, "charsel_start.png") is None,
                             timeout=30.0, first_wait=1.0):
        rd.step("選角畫面按「開始遊戲」一直沒反應")
        return False
    rd.step("按了「開始遊戲」，等進到遊戲")
    if not wait_until(lambda sc: on_main(sc), 90.0):
        back_to_main()                               # 進遊戲常會跳公告、簽到，關掉
    if not on_main():
        rd.step("進遊戲後回不到主畫面")
        return False
    rd.wake_up()
    rd.step(f"已經換成第 {slot} 隻")
    return True


def _foot(screen=None):
    """看腳印是「已跟隨」（有斜線）還是「沒跟隨」。回傳 ("on"/"off"/None, 框)。

    兩張模板只差一條細斜線，以前看到 follow_on 就算數 → 沒跟隨也常被當成已跟隨（使用者實測）。
    現在兩張都比，哪張分數高算哪張；一樣高算「沒跟隨」（多按一下會被後面的確認抓到再按回來）。"""
    screen = grab() if screen is None else screen
    on = find_one(screen, "follow_on.png")
    off = find_one(screen, "follow_off.png")
    if on and off:
        return ("on", on) if on[4] > off[4] else ("off", off)
    if on:
        return "on", on
    if off:
        return "off", off
    return None, None


def _open_leader_foot():
    """隊伍面板 → 點隊長（紅色星星）→ 等 2 秒讓腳印出現穩定 → 看腳印。
    回傳 ("on"/"off"/None, 框)，或 "out"（不在隊裡）、"nostar"（找不到隊長）。面板留著開。"""
    st = party_status()
    if st != "in":
        back_to_main()
        return "out"
    star = wait_for("leader_star.png", timeout=3.0)
    if not star:
        rd.step("隊伍面板裡找不到隊長的紅色星星")
        back_to_main()
        return "nostar"
    click_box(star, wait=rd.T_PANEL_MAX)
    rd.nap(2.0)                                       # 使用者要求：點了隊長等 2 秒再看、再按
    for _ in range(int(6 * max(1.0, rd.SLOW))):
        state, box = _foot()
        if state:
            return state, box
        time.sleep(0.5)
    return None, None


def follow_leader():
    """隊伍面板 → 點隊長 → 看腳印：已跟隨就不按；沒跟隨就按，再打開確認，還沒跟隨最多再按 2 次。
    回傳有沒有在跟隨。"""
    for attempt in range(3):                          # 第 1 次 ＋ 最多再按 2 次
        r = _open_leader_foot()
        if r in ("out", "nostar"):
            return False
        state, box = r
        if state == "on":
            rd.step("已經在跟隨隊長了（腳印有斜線，不按）" if attempt == 0
                    else f"跟隨成功（按了 {attempt} 次腳印）")
            back_to_main()
            return True
        if not state:
            rd.step("點了隊長，但沒看到腳印")
            back_to_main()
            return False
        if attempt:
            rd.step(f"還沒在跟隨，再按一次腳印（第 {attempt + 1} 次）")
        click_box(box, wait=rd.T_PANEL_MAX)           # 沒斜線的腳印 → 按下去開始跟隨
        rd.step("按了腳印，重新打開確認有沒有變成「已跟隨」")
        back_to_main()
    r = _open_leader_foot()                           # 按了 3 次，最後再確認一次
    ok = isinstance(r, tuple) and r[0] == "on"
    back_to_main()
    rd.step("跟隨成功（按了 3 次腳印）" if ok else "按了 3 次腳印還是看不到「已跟隨」")
    return ok


def chat_page():
    """打開對話框「系統」頁，回傳 (有沒有「獲得燃料」, 那一頁的畫面)；打不開回傳 (None, None)。"""
    if not P_CHAT_OPEN:
        rd.step("⚠ 還沒校正「左下對話框」的位置，沒辦法看燃料")
        return None, None
    rd.step("點開左下對話框")
    click_at(P_CHAT_OPEN[0], P_CHAT_OPEN[1], wait=rd.T_PANEL_MAX)
    # 對話框開著時上方的圖示還看得到（on_main 還是 True），所以用「系統」分頁判斷有沒有打開
    tab = wait_for("chat_sys_tab.png", timeout=4.0)
    if not tab:
        rd.step(f"⚠ 對話框打不開（等 4 秒沒看到「系統」分頁；{dump_fail('fuel_chat_open')}）")
        return None, None
    rd.step(f"切到「系統」頁（{tab[4]:.2f} 分）")
    click_box(tab, wait=1.0)
    wait_stable(1.0)
    sc = grab()
    hit = find_one(sc, "chat_fuel.png")
    near = hit or find_one(sc, "chat_fuel.png", threshold=0.3)
    fuel = hit is not None
    rd.step(f"系統頁：{'有' if fuel else '沒有'}「獲得燃料」"
            f"（最像 {near[4] if near else 0.0:.2f} 分，要 {rd.MATCH_THRESHOLD:g}）")
    page = _region(sc, 0.0, 0.10, 0.45, 0.95).copy()
    closed = False
    for _ in range(3):                                # 用收起箭頭關掉，確認「系統」分頁不見了
        x = find_one(grab(), "chat_close.png")
        if not x:
            closed = True
            break
        click_box(x, wait=1.0)
        if not find_one(grab(), "chat_sys_tab.png"):
            closed = True
            break
    rd.step("收起對話框" if closed else "⚠ 對話框收不起來（chat_close 可能要重抓）")
    return fuel, page


def _area_changed(before, after, x, y, half):
    """拖曳點附近那一塊有沒有變（沒變 = 捲到底了）。"""
    try:
        import numpy as np
        h, w = before.shape[:2]
        x0, x1 = max(0, x - half), min(w, x + half)
        y0, y1 = max(0, y - half), min(h, y + half)
        a = before[y0:y1, x0:x1].astype("int16")
        b = after[y0:y1, x0:x1].astype("int16")
        return float(np.abs(a - b).mean()) > 2.0
    except Exception:
        return True


def _bag_find_fuel():
    """在包包愛心分頁找燃料。第一頁沒有、又有抓拖曳起點，就上下捲來找。

    使用者要愛心放很多東西，燃料會被擠到下面。遊戲可能記住上次捲到哪，
    所以先往上捲回頂端（邊捲邊找），再往下捲到底（邊捲邊找）。拖不動 = 到底了。
    找不到時把「最像燃料」的那一刻畫面存起來、紀錄寫分數（使用者怕「燃料在畫面上但沒認出來」，2026.11.06r）。"""
    best = {"score": 0.0, "img": None}

    def look(screen):
        hit = find_one(screen, "fuel_item.png")
        if hit:
            return hit
        near = find_one(screen, "fuel_item.png", threshold=0.3)   # 只是拿分數，不當作找到
        if near and near[4] > best["score"]:
            best["score"], best["img"] = near[4], screen
        elif best["img"] is None:
            best["img"] = screen
        return None

    item = wait_for("fuel_item.png", timeout=4.0)
    if item:
        rd.step(f"愛心分頁第一頁就看到燃料（{item[4]:.2f} 分）")
        return item
    look(grab())
    if P_BAG_SCROLL:
        x, y = P_BAG_SCROLL
        d = int(rd.AREA_W * 150 / 800)                # 一次拖多遠（800 寬時 150）
        rd.step("愛心分頁第一頁沒看到燃料，上下捲來找")
        for direction, name in ((1, "上"), (-1, "下")):  # 往下拖 = 看上面；往上拖 = 看下面
            for i in range(1, 7):
                before = grab()
                rd.drag_line(x, y, x, y + direction * d, steps=16, hold=0.03)
                after = grab()
                item = look(after)
                if item:
                    rd.step(f"往{name}捲第 {i} 次：找到燃料")
                    return item
                if not _area_changed(before, after, x, y, d):
                    break                             # 到頂／到底了
    # 還是找不到：存「最像的那一刻」，寫分數
    path = ""
    try:
        os.makedirs(rd.SHOT_DIR, exist_ok=True)
        path = os.path.join(rd.SHOT_DIR, "fail_fuel_bag.png")
        rd.imwrite(path, best["img"] if best["img"] is not None else grab())
    except Exception:
        path = ""
    sc = best["score"]
    verdict = ("有點像但不夠像，燃料可能在畫面上卻沒認出來 → 到校正頁重抓燃料那張圖" if sc >= 0.6
               else "看起來真的不在愛心分頁（可能沒設愛心，或這隻還沒有燃料）")
    rd.step(f"整個愛心分頁最像燃料的只有 {sc:.2f} 分（要 {rd.MATCH_THRESHOLD:g} 以上）：{verdict}"
            + (f"（{path}）" if path else ""))
    return None


def bag_fuel_full():
    """包包 → 愛心分頁 → 點燃料 → 有沒有「2000/2000」。回傳 True / False / None（看不到燃料）。"""
    if not on_main():
        back_to_main()
    if rd.HOTKEYS:
        rd.step(f"打開包包（按 {BAG_KEY.upper()}）")
        pyautogui.press(BAG_KEY)
        rd.nap(0.6)
    if on_main() and P_BAG_BTN:
        rd.step("打開包包（點包包按鈕）")
        click_at(P_BAG_BTN[0], P_BAG_BTN[1], wait=rd.T_PANEL_MAX)
    wait_stable(1.5)
    if P_BAG_FAV:
        rd.step("點包包的愛心分頁")
        click_at(P_BAG_FAV[0], P_BAG_FAV[1], wait=1.0)
    else:
        rd.step("⚠ 還沒校正「包包裡的愛心分頁」位置")
    item = _bag_find_fuel()
    if not item:
        rd.step("包包愛心分頁裡找不到燃料" + ("（上下都捲過了）" if P_BAG_SCROLL else
                "（燃料如果在下面，到校正頁「燃料輪替」抓「包包物品格子區的正中間」，程式就會捲下去找）"))
        back_to_main()
        return None
    rd.step(f"點燃料看數量（燃料 {item[4]:.2f} 分）")
    click_box(item, wait=1.0)
    hit = wait_for("fuel_full.png", timeout=3.0)
    full = hit is not None
    if full:
        rd.step(f"看到「2000/2000」（{hit[4]:.2f} 分）→ 燃料滿了")
    if not full:
        # 朋友實測：一直開包包、一直說還沒 2000、不換下一隻。可能真的還沒滿，也可能「2000/2000」那張圖
        # （使用者分享的）在他電腦上比不到。把最像的分數寫出來，太像的話存截圖（2026.11.11d）。
        screen = grab()
        near = find_one(screen, "fuel_full.png", threshold=0.3)
        sc = near[4] if near else 0.0
        if sc >= 0.6:
            path = ""
            try:
                os.makedirs(rd.SHOT_DIR, exist_ok=True)
                path = os.path.join(rd.SHOT_DIR, "fail_fuel_full.png")
                rd.imwrite(path, screen)
            except Exception:
                path = ""
            rd.step(f"燃料看起來還沒 2000，但「2000/2000」那張圖有 {sc:.2f} 分像（要 {rd.MATCH_THRESHOLD:g}）："
                    "如果其實已經 2000，請到校正頁「燃料輪替」重抓「2000/2000」那張圖"
                    + (f"（{path}）" if path else ""))
        else:
            rd.step(f"燃料還沒 2000（「2000/2000」最像只有 {sc:.2f} 分）")
    rd.step("關包包、回主畫面")
    back_to_main()
    return full


class FuelAccount:
    """一個帳號（視窗）：依序換角色、入隊、跟隨、看燃料。"""

    def __init__(self, hwnd, slots=(2, 3, 1)):
        self.hwnd = hwnd
        self.label = rd.window_label(hwnd)
        done = rd.done_today(_fuel_key(hwnd))
        slots = set(slots or (2, 3, 1))                  # 這個帳號要吸的角色（GUI 選擇視窗勾的）
        self.queue = [n for n in (2, 3, 1) if n in slots and f"slot{n}" not in done]   # 先小號，最後本尊
        self.back_to_main = 1 not in slots               # 沒勾本尊：全部吸完換回本尊
        self.state = F_DONE if not self.queue else F_WAIT
        self.slot = None              # 目前在吸的是第幾隻
        self.current = None           # 遊戲裡現在登入的是第幾隻（換過才知道）
        self.errors = 0
        self.extra = ""               # 收尾的結果（換回本尊）
        self.last_fuel = 0.0          # 上次在對話框看到「獲得燃料」的時間
        self.since = 0.0              # 這一隻進隊的時間（算吸了幾分鐘）
        self.page = None              # 上次看到的對話框
        self.stuck = 0
        self.fixes = 0
        self.last = 0.0
        self.note = "今天已經全部完成（紀錄）" if not self.queue else ""
        self.picked = "、".join({2: "第2隻", 3: "第3隻", 1: "本尊"}[n] for n in (2, 3, 1) if n in slots)

    @property
    def next_is_main(self):
        return bool(self.queue) and self.queue[0] == 1

    def finish_slot(self, why):
        rd.mark_done(f"slot{self.slot}", _fuel_key(self.hwnd))
        rd.step(f"第 {self.slot} 隻{why}")
        self.queue.pop(0)
        self.slot, self.page, self.stuck, self.fixes = None, None, 0, 0
        self.state = F_DONE if not self.queue else F_WAIT
        if not self.queue:
            self.note = "全部完成"
            self.wrap_up()

    def wrap_up(self):
        """這個帳號要吸的都吸完了。沒勾本尊的話換回本尊（隔天跑每日任務登入的才是本尊）。"""
        if not self.back_to_main or self.current in (None, 1):
            return                                    # 本尊本來就在輪替裡，或這次根本沒換過角色
        rd.step("要吸的角色都完成了，換回本尊")
        if switch_character(1) is True:
            self.current = 1
            self.extra = "，已換回本尊"
        else:
            self.extra = f"，⚠ 換回本尊失敗，請手動換（{dump_fail(f'fuel_{self.label}_back')}）"

    def start_next(self):
        """有空位了：換到下一隻 → 確認還沒滿 → 入隊 → 跟隨。回傳有沒有佔到一個位置。"""
        while self.queue:
            slot = self.queue[0]
            self.slot = slot
            switched = False
            if self.current != slot:                  # 已經是這隻（上次入隊沒成功）就不用再換一次
                r = switch_character(slot)
                if r == "empty":
                    self.queue.pop(0)
                    continue
                if not r:
                    self.errors += 1
                    self.last = time.time() + 120     # 失敗了等 2 分鐘再試
                    shot = dump_fail(f"fuel_{self.label}_switch")
                    if self.errors >= 3:
                        self.state = F_DONE
                        self.note = f"⚠ 換第 {slot} 隻失敗 3 次，這個帳號先跳過（{shot}）"
                    else:
                        self.state, self.note = F_ERR, f"換不到第 {slot} 隻，2 分鐘後再試（{shot}）"
                    return False
                self.current = slot
                switched = True
            # 使用者要求：換好角色馬上入隊、跟隨，不要先開包包看（他會先把隊伍位置空出來）。
            # 已經滿了的角色，1 分鐘後第一次巡邏會發現（對話框沒有「獲得燃料」→ 開包包看 2000；本尊看戰鬥次數）再離隊。
            # 剛換好角色一定不在隊伍裡 → 直接去好友申請（使用者要求，不要先開隊伍面板又關掉）。
            # 只有「沒換角色、重試申請」時才先看一下，可能上次其實已經進去了。
            st = "out"
            if not switched:
                st = party_status()
                back_to_main()
            if st != "in" and not apply_party():
                self.last = time.time() + 60          # 隊伍可能剛好滿了：1 分鐘後再申請（不用再換角色）
                self.state, self.note = F_WAIT, "申請入隊沒進去（可能隊伍剛好滿了），1 分鐘後再試"
                return False
            followed = follow_leader()
            self.state, self.page, self.stuck, self.errors = F_IN, None, 0, 0
            self.since, self.last_fuel = time.time(), 0.0
            self.last = time.time() + FUEL_FIRST_WAIT - FUEL_GAP   # 巡邏是「上次 + FUEL_GAP」才看 → 等於 1 分鐘後才第一次看
            self.note = (f"第 {slot} 隻{'（本尊）' if slot == 1 else ''}進隊跟隨了，"
                         f"{FUEL_FIRST_WAIT:g} 秒後第一次看有沒有獲得燃料"
                         + ("" if followed else "（跟隨還沒成功，巡邏時會再試）"))
            return True
        self.state, self.note = F_DONE, "全部完成"
        self.wrap_up()
        return False

    def check(self):
        """巡一次：滿了就離隊換下一隻；沒新訊息就修跟隨。回傳有沒有空出一個位置。"""
        is_main = self.slot == 1
        if is_main and count_is_full():
            party_status()
            if leave_party():
                self.finish_slot("（本尊）戰鬥次數 10000 打滿，已離隊")
                self.note = "全部完成"
                return True
            self.note = "本尊打滿了但離隊失敗"
            return False
        fuel, page = chat_page()
        if page is None:
            self.note = "對話框打不開"
            return False
        first = self.page is None                     # 進隊後第一次看
        changed = not _same(page, self.page)
        self.page = page
        if fuel:
            self.last_fuel = time.time()
        seen = (f"上次看到燃料是 {time.strftime('%H:%M:%S', time.localtime(self.last_fuel))}"
                if self.last_fuel else "還沒看到過燃料")
        rd.step("進隊後第一次看對話框" if first else
                f"對話框跟上次{'不一樣（有新訊息）' if changed else '一樣（沒有新訊息）'}；{seen}")
        if changed:
            self.stuck = 0
            if fuel or is_main:
                self.note = ("有獲得燃料，" if first and fuel else "") + "還在吸" \
                    + ("（本尊等戰鬥次數 10000）" if is_main else "")
                return False
            rd.step("進隊後第一次看：對話框沒有「獲得燃料」，打開包包看是不是已經 2000" if first
                    else "對話框有新訊息但沒有燃料：可能滿了，打開包包確認")
            full = bag_fuel_full()
            if full:
                party_status()
                if leave_party():
                    self.finish_slot("燃料 2000 滿了，已離隊")
                    return True
                self.note = "燃料滿了但離隊失敗"
                return False
            self.note = "包包還沒 2000，繼續吸" if full is False else "包包裡看不到燃料"
            return False
        self.stuck += 1
        if self.stuck < 2:
            self.note = "對話框這次沒有新訊息，下次再看"
            return False
        # 連續兩次沒有新訊息：不在隊裡？沒跟隨？
        self.fixes += 1
        rd.step("對話框一直沒有新訊息：檢查還在不在隊裡、有沒有在跟隨")
        st = party_status()
        back_to_main()
        if st == "out":
            if apply_party():
                follow_leader()
                self.note = "掉出隊伍了，已重新入隊並跟隨"
            else:
                self.note = "掉出隊伍了，重新申請沒進去"
        elif follow_leader():
            self.note = "有在跟隨，但沒有新訊息：打手可能沒在打怪"
        else:
            self.note = "跟隨失敗"
        self.stuck = 0
        if self.fixes >= 4:
            self.note += f"（⚠ 已經修了 {self.fixes} 次還是沒動靜，請看一下）"
        return False


class _SlowActions:
    """燃料輪替跑的時候，每一次點擊、按鍵之後都停 FUEL_ACTION_GAP 秒。

    程式所有的點擊都經過 pyautogui.click、按鍵經過 pyautogui.press／hotkey，
    所以只要在這段時間把這三個換成「做完再停一下」的版本，結束時（包括中止、出錯）換回來，
    每日任務、組隊輪替的速度都不受影響。"""

    NAMES = ("click", "press", "hotkey")

    def __init__(self, gap):
        self.gap = gap
        self.orig = {}

    def __enter__(self):
        if self.gap <= 0:
            return self
        for name in self.NAMES:
            fn = getattr(pyautogui, name)
            self.orig[name] = fn

            def slow(*a, _fn=fn, **k):
                r = _fn(*a, **k)
                time.sleep(self.gap)
                return r
            setattr(pyautogui, name, slow)
        return self

    def __exit__(self, *exc):
        for name, fn in self.orig.items():
            setattr(pyautogui, name, fn)
        self.orig = {}
        return False


def fuel_run(leader=None, accounts=None, slots=None):
    """GUI 從彈窗選好打手和要吸的帳號傳進來。slots = {視窗: (要吸的角色, 例如 (2, 3))}，沒給就三隻都吸。"""
    home = rd.ACTIVE_PROFILE
    try:
        rd.STEP_TIME = True                           # 燃料輪替的步驟前面加時間
        with _SlowActions(FUEL_ACTION_GAP):
            _fuel_run(leader, accounts or [], slots or {})
    finally:
        rd.STEP_TIME = False
        rd.use_profile(home)
        _load()


def _fuel_ready(kind):
    missing = [f for f in FUEL_TEMPLATES if not has(f)]
    if missing:
        party_group = {"friend_close.png"}
        a = [f for f in missing if f not in party_group]
        b = [f for f in missing if f in party_group]
        print(f"【{kind}】燃料輪替缺少模板："
              + (("、".join(a) + "（校正頁「燃料輪替」那組）") if a else "")
              + ("；" if a and b else "")
              + (("、".join(b) + "（校正頁「組隊輪替」那組：好友面板的 ✕）") if b else ""))
        return False
    lacks = [n for n, pt in zip((1, 2, 3), P_CHAR_SLOTS) if not pt]
    if lacks or not P_CHAT_OPEN or not P_BAG_FAV or not P_AVATAR:
        print(f"【{kind}】燃料輪替的位置還沒校正完（選角頭像、對話框、包包愛心分頁、自己的頭像）")
        return False
    if not rd.HOTKEYS and not (P_PARTY_BTN and P_FRIEND_BTN and P_BAG_BTN):
        print(f"【{kind}】沒有快捷鍵：請抓「隊伍」「好友」「包包」按鈕的位置")
        return False
    return True


def _fuel_run(leader, accounts, slots=None):
    import win32gui
    if not accounts:
        print("沒有要吸燃料的帳號")
        return
    for k in sorted({rd.kind_of(h) for h in accounts}, key=lambda k: rd.PROFILE_NAMES.index(k)):
        rd.use_profile(k)
        _load()
        if not _fuel_ready(k):
            return
    accs = []
    for h in accounts:
        _use(h)
        accs.append(FuelAccount(h, (slots or {}).get(h) or (2, 3, 1)))
    print(f"打手：{rd.window_label(leader) if leader else '（不在這台電腦）'}，"
          f"{len(accs)} 個帳號，同時最多 {FUEL_MAX} 隻在吸，每個視窗至少隔 {FUEL_GAP:g} 秒看一次，"
          f"每個動作後停 {FUEL_ACTION_GAP:g} 秒")
    for a in accs:
        print(f"  {a.label}：吸 {a.picked or '（沒勾）'}"
              + ("，吸完換回本尊" if a.back_to_main else "")
              + (f"　→ {a.note}" if a.state == F_DONE else ""))
    t0 = time.time()

    def visit(a, what):
        orig = rd.remember_place(a.hwnd)
        try:
            _use(a.hwnd)
            rd.step("切到這個視窗，搬到左上角")
            rd.normalize_window(a.hwnd)
            if on_main():
                rd.wake_up()
            elif what == "check":
                rd.step("不在主畫面，先回主畫面")
            if not on_main() and what == "check" and not back_to_main():
                a.note = f"不在主畫面（{dump_fail(f'fuel_{a.label}_start')}）"
                return False
            return a.start_next() if what == "start" else a.check()
        except (pyautogui.FailSafeException, rd.Aborted):
            raise
        except Exception as e:
            a.note = f"發生錯誤：{e}"
            try:
                back_to_main()
            except Exception:
                pass
            return False
        finally:
            a.last = max(a.last, time.time())        # 失敗時設的「等一下再試」不要被蓋掉
            try:
                rd.restore_place(a.hwnd, orig)
                rd.step("視窗放回原位")
            except Exception:
                pass

    def mins(a):
        return f"已 {(time.time() - a.since) / 60:.0f} 分鐘" if a.state == F_IN and a.since else ""

    def head(a, text):
        who = f"第 {a.slot} 隻" if a.slot else "（還沒換）"
        extra = mins(a)
        print(f"\n──── {time.strftime('%H:%M:%S')}　{a.label}｜{who}｜{text}"
              + (f"（{extra}）" if extra else "") + " ────", flush=True)

    def table():
        print(f"\n======== {time.strftime('%H:%M:%S')} 總表（已跑 {(time.time() - t0) / 60:.0f} 分鐘）========")
        for a in accs:
            who = f"第 {a.slot} 隻" if a.slot else ""
            left = "、".join({2: "第2隻", 3: "第3隻", 1: "本尊"}[n] for n in a.queue) or "沒有"
            note = (a.note or "—").splitlines()[0]
            note = note if len(note) <= 60 else note[:60] + "…"
            print(f"  {a.label}　{who}　{a.state}　{mins(a)}　還要吸：{left}　上次：{note}")
        print("=" * 40, flush=True)
    last_table = time.time()

    try:
        while True:
            if rd.ABORT:
                print("已中止")
                return
            alive = [a for a in accs if a.state != F_DONE and win32gui.IsWindow(a.hwnd)]
            if not alive:
                print(f"\n所有帳號都完成了，共 {(time.time() - t0) / 60:.0f} 分鐘。")
                for a in accs:
                    print(f"  {a.label}（{a.picked}）：{a.note}{a.extra}")
                return
            busy = sum(1 for a in accs if a.state == F_IN)
            did = False
            # 有空位：優先給下一隻是小號的帳號（小號快，本尊佔位置很久）
            waiting = sorted([a for a in alive if a.state in (F_WAIT, F_ERR)
                              and time.time() - a.last >= FUEL_GAP],
                             key=lambda a: a.next_is_main)
            if busy < FUEL_MAX and waiting:
                a = waiting[0]
                nxt = {2: "第2隻", 3: "第3隻", 1: "本尊"}.get(a.queue[0] if a.queue else 0, "")
                head(a, f"有空位（{busy}/{FUEL_MAX}），換下一隻進隊：{nxt}")
                visit(a, "start")
                print(f"  {time.strftime('%H:%M:%S')} → {a.note}", flush=True)
                did = True
            for a in [a for a in alive if a.state == F_IN]:
                if rd.ABORT:
                    break
                if time.time() - a.last < FUEL_GAP:
                    continue
                head(a, "巡邏：看燃料")
                freed = visit(a, "check")
                print(f"  {time.strftime('%H:%M:%S')} → {a.note}", flush=True)
                did = True
                if freed:
                    break                             # 空出位置了，先回去讓下一隻進隊
            if not did:
                time.sleep(1)
            if time.time() - last_table >= 300:           # 每 5 分鐘印一次總表
                table()
                last_table = time.time()
    except rd.Aborted:
        print("\n已中止，視窗已還原。")


if __name__ == "__main__":
    rd.enable_dpi_awareness()
    rd.start_stop_hotkey()
    args = sys.argv[1:]
    num = next((int(a) for a in args if a.isdigit()), None)
    run(once=("once" in args), only=num)
