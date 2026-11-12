#!/usr/bin/env python3
"""Yahoo!メール（Yahoo! JAPAN）の受信箱で、緊急・重要なもの以外の未読メールを既読にする。

判定の順番:
    1. rules.txt の【必ず既読】に当たる → 既読、【必ず残す】に当たる → 未読のまま（Jev に聞かない）
    2. Jev（TypeSafe AI）に「未読で残すべきか」の確率を聞き、【数値】の「残す確率」以上なら未読のまま
    3. Jev のキーがない・エラー・1回の上限超えのときは、【緊急キーワード】で判定
    一度「残す」と決めたメールは記録し、次回からは Jev に聞き直さない（費用を抑えるため）。

使い方:
    python3 sort_yahoo_mail.py                    # お試し（何も変えず、件数と残すメールの件名を表示）
    python3 sort_yahoo_mail.py --run              # 実際に既読にする
    python3 sort_yahoo_mail.py --restore-folders  # 以前の振り分けで作ったフォルダのメールを受信箱に戻し、フォルダを消す

ルールは ../rules.txt を書き換えて変える（コードを触らなくてよい）。

ログイン情報は、環境変数 YAHOO_USER / YAHOO_PASS → macOS キーチェーン
（setup_mac.sh で保存）→ 画面での入力、の順に探す。
Jev の API キーは、環境変数 TYPESAFE_API_KEY → キーチェーン（サービス名 typesafe-api-key）の順に探す。

事前準備:
    Yahoo!メールの「設定 → IMAP/POP/SMTPアクセス」で IMAP を「利用する」にし、
    「Yahoo! JAPAN公式サービス以外からのアクセスも有効にする」をオンにする。
"""
import argparse
import base64
import datetime
import email
import email.header
import getpass
import html
import imaplib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

HOST = "imap.mail.yahoo.co.jp"
KEYCHAIN_SERVICE = "yahoo-mail-sorter"
JEV_KEYCHAIN_SERVICE = "typesafe-api-key"

# Jev（TypeSafe AI の判断特化モデル）。形式は https://docs.typesafe.ai/primitives/noul
JEV = {
    "url": "https://api.typesafe.ai/v1/systemone",
    "model": "jev-latest",
    "body_chars": 300,   # Jev に渡す本文の文字数
}
# 既読ルール（必ず既読・必ず残す・緊急キーワード・Jev に伝えること・数値）は rules.txt に書く
RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rules.txt")

# 一度「残す」と決めたメールの記録（Jev に聞き直さないため）
STATE_FILE = os.path.expanduser("~/.yahoo-mail-sorter-state.json")

# 以前の振り分け機能で作ったフォルダ（--restore-folders で受信箱に戻す）
OLD_FOLDERS = ["要確認", "買い物", "会員登録", "メルマガ"]


def load_rules(path=RULES_FILE):
    """rules.txt を読む。[見出し] の下に1行1つ。# で始まる行は無視。"""
    sections, cur = {}, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.fullmatch(r"\[(.+)\]", line)
            if m:
                cur = sections.setdefault(m.group(1).strip(), [])
            elif cur is not None:
                cur.append(line)
    nums = {}
    for line in sections.get("数値", []):
        if "=" in line:
            k, v = line.split("=", 1)
            nums[k.strip()] = v.strip()
    return {
        "always_read": sections.get("必ず既読", []),
        "always_keep": sections.get("必ず残す", []),
        "urgent": sections.get("緊急キーワード", []),
        "profile": "\n".join(sections.get("Jevに伝えること", [])),
        "keep_threshold": float(nums.get("残す確率", 0.5)),
        "jev_max": int(nums.get("Jevの上限", 100)),
    }


def contains_any(words, subject, sender):
    s, f = subject.lower(), sender.lower()
    return any(w.lower() in s or w.lower() in f for w in words)


def imap_utf7_encode(s):
    """フォルダ名を IMAP 用の文字コード（modified UTF-7）に変換する。"""
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=")
            out.append("&" + b.replace("/", ",") + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def quote(name):
    return '"' + imap_utf7_encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


def decode_header(value):
    if not value:
        return ""
    parts = []
    for text, enc in email.header.decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                parts.append(text.decode("utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def keychain_password(service):
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def get_jev_key():
    return os.environ.get("TYPESAFE_API_KEY") or keychain_password(JEV_KEYCHAIN_SERVICE)


def body_text(msg):
    """本文の冒頭をテキストで返す（text/plain 優先、なければ HTML からタグを除く）。"""
    plain, htm = None, None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_filename():
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        except (LookupError, AssertionError):
            continue
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and htm is None:
            htm = html.unescape(re.sub(r"(?s)<(style|script).*?</\1>|<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", plain or htm or "").strip()


def ask_jev(key, profile, sender, subject, body):
    """未読で残すべき確率（0〜1）を返す。失敗したら (None, 理由)。"""
    payload = {
        "model": JEV["model"],
        "state": "\n".join([f"差出人: {sender}", f"件名: {subject}",
                            f"本文冒頭: {body[:JEV['body_chars']]}"]),
        "questions": {
            "keepUnread": {
                "type": "noul",
                "instructions": profile + "\nこのメールは、緊急度や重要度が高く、未読で残して本人が読むべきか？",
                "criteria": {
                    "true": "本人がすぐ確認・対応すべきもの（認証コード、セキュリティ警告、支払い、予約・手続き、人からの連絡）",
                    "false": "お知らせ・広告・メルマガ・自動通知など、読まずに既読にしてよいもの",
                },
            },
        },
    }
    req = urllib.request.Request(
        JEV["url"], data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return None, f"エラー {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:  # ネットワークや JSON の失敗
        return None, f"呼び出し失敗: {e}"
    # 返答は { "answers": { "keepUnread": { "type": "noul", "noul": 0.93 } } }
    p = (data.get("answers") or {}).get("keepUnread", {}).get("noul")
    if not isinstance(p, (int, float)):
        return None, "返答から確率を読めない: " + json.dumps(data, ensure_ascii=False)[:200]
    return float(p), None


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def keychain_login():
    """macOS のキーチェーンから ID とパスワードを読む。なければ (None, None)。"""
    try:
        info = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
                              capture_output=True, text=True)
        pw = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                            capture_output=True, text=True)
    except FileNotFoundError:
        return None, None
    m = re.search(r'"acct"<blob>="([^"]*)"', info.stdout)
    if info.returncode or pw.returncode or not m:
        return None, None
    return m.group(1), pw.stdout.rstrip("\n")


def get_login():
    user, password = os.environ.get("YAHOO_USER"), os.environ.get("YAHOO_PASS")
    if user and password:
        return user, password
    user, password = keychain_login()
    if user and password:
        return user, password
    if not sys.stdin.isatty():
        sys.exit("ログイン情報が見つかりません。setup_mac.sh を実行してキーチェーンに保存してください。")
    return input("Yahoo! JAPAN ID またはメールアドレス: "), getpass.getpass("パスワード: ")


def chunks(items, n=200):
    for i in range(0, len(items), n):
        yield b",".join(items[i:i + n])


def restore_folders(m):
    for folder in OLD_FOLDERS:
        typ, _ = m.select(quote(folder))
        if typ != "OK":
            continue
        typ, data = m.uid("search", None, "ALL")
        uids = data[0].split()
        moved = 0
        for chunk in chunks(uids):
            typ, _ = m.uid("copy", chunk, "INBOX")
            if typ == "OK":
                m.uid("store", chunk, "+FLAGS", r"(\Deleted)")
                moved += chunk.count(b",") + 1
        m.expunge()
        m.close()
        if moved == len(uids):
            m.delete(quote(folder))
            print(f"「{folder}」の {moved} 通を受信箱に戻し、フォルダを消しました")
        else:
            print(f"「{folder}」: {len(uids)} 通中 {moved} 通だけ戻せました（フォルダは残しています）")


def mark_read(m, run):
    typ, data = m.select("INBOX")
    typ, uv = m.response("UIDVALIDITY")
    uidvalidity = (uv[0] or b"").decode()
    typ, data = m.uid("search", None, "UNSEEN")
    uids = data[0].split()

    state = load_state()
    if state.get("uidvalidity") != uidvalidity:
        state = {"uidvalidity": uidvalidity, "keep": {}}
    keep_known = state["keep"]  # uid -> 判定の理由

    rules = load_rules()
    jev_key = get_jev_key()
    jev_calls, jev_error = 0, None
    keep, to_read = [], []  # keep: (件名, 理由)
    counts = {"ルール": 0, "Jev": 0, "キーワード": 0, "前回の判定": 0}

    for chunk in chunks(uids, 50):
        typ, resp = m.uid("fetch", chunk, "(UID BODY.PEEK[]<0.30000>)")
        for item in resp:
            if not isinstance(item, tuple):
                continue
            uid = re.search(rb"UID (\d+)", item[0]).group(1)
            msg = email.message_from_bytes(item[1])
            subject = decode_header(msg.get("Subject"))
            sender = decode_header(msg.get("From"))
            key = uid.decode()

            if contains_any(rules["always_read"], subject, sender):
                counts["ルール"] += 1
                to_read.append(uid)
                continue
            if contains_any(rules["always_keep"], subject, sender):
                counts["ルール"] += 1
                keep.append((subject, "必ず残す"))
                continue
            if key in keep_known:
                counts["前回の判定"] += 1
                keep.append((subject, keep_known[key]))
                continue

            p = None
            if jev_key and jev_calls < rules["jev_max"]:
                jev_calls += 1
                p, err = ask_jev(jev_key, rules["profile"], sender, subject, body_text(msg))
                if err:
                    jev_error = err
            if p is not None:
                counts["Jev"] += 1
                urgent, why = p >= rules["keep_threshold"], f"Jev {p:.2f}"
            else:
                counts["キーワード"] += 1
                urgent, why = contains_any(rules["urgent"], subject, sender), "キーワード"

            if urgent:
                keep.append((subject, why))
                keep_known[key] = why
            else:
                to_read.append(uid)

    print(f"受信箱の未読: {len(uids)} 通")
    print(f"  既読にする: {len(to_read)} 通")
    print(f"  未読のまま残す: {len(keep)} 通")
    for subj, why in keep[:30]:
        print(f"    - [{why}] {subj[:60]}")
    if len(keep) > 30:
        print(f"    …ほか {len(keep) - 30} 通")
    print("  判定のしかた: " + "、".join(f"{k} {v}通" for k, v in counts.items() if v))
    if not jev_key:
        print("  ※ Jev の API キーが見つからないので、キーワードで判定しました")
    if jev_error:
        print(f"  ※ Jev でエラーがあり、その分はキーワードで判定しました（最後のエラー: {jev_error}）")
    if jev_key and jev_calls >= rules["jev_max"]:
        print(f"  ※ Jev は1回 {rules['jev_max']} 通までなので、残りはキーワードで判定しました")

    if not run:
        print("\nお試しモードなので何も変えていません。実行するには --run を付けてください。")
        return
    for chunk in chunks(to_read):
        m.uid("store", chunk, "+FLAGS", r"(\Seen)")
    state["keep"] = {k: v for k, v in keep_known.items() if k.encode() in set(uids)}
    save_state(state)
    print("既読にしました")


def main():
    ap = argparse.ArgumentParser(description="Yahoo!メールの、緊急・重要なもの以外を既読にする")
    ap.add_argument("--run", action="store_true", help="実際に既読にする（付けないとお試しのみ）")
    ap.add_argument("--restore-folders", action="store_true",
                    help="以前の振り分けフォルダのメールを受信箱に戻し、フォルダを消す")
    args = ap.parse_args()

    user, password = get_login()
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "開始")
    m = imaplib.IMAP4_SSL(HOST, 993)
    m.login(user, password)

    if args.restore_folders:
        restore_folders(m)
    else:
        mark_read(m, args.run)
    m.logout()


if __name__ == "__main__":
    main()
