"use strict";

// 表示はすべて textContent / value で行い、innerHTML は使わない（ページ由来の文字列を HTML として解釈させない）。

const $ = (id) => document.getElementById(id);
const els = {
  title: $("title"),
  meta: $("meta"),
  output: $("output"),
  copy: $("copy"),
  save: $("save"),
  status: $("status"),
  withSource: $("withSource"),
};

let result = null; // { title, url, text, markdown, truncated }

const setStatus = (msg, isError = false) => {
  els.status.textContent = msg;
  els.status.classList.toggle("error", isError);
};

const fail = (msg) => {
  els.title.textContent = "取り出せませんでした";
  els.meta.textContent = "";
  els.output.value = "";
  setStatus(msg, true);
};

const format = () => document.querySelector("input[name=format]:checked").value;

// YAML のダブルクォート文字列として安全な形にする
const yamlString = (s) =>
  '"' + s.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';

const today = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const build = () => {
  if (!result) return "";
  const md = format() === "markdown";
  const body = md ? result.markdown : result.text;
  if (!els.withSource.checked) return body;
  if (md) {
    return [
      "---",
      `title: ${yamlString(result.title)}`,
      `source: ${yamlString(result.url)}`,
      `clipped: ${today()}`,
      "---",
      "",
      body,
    ].join("\n");
  }
  return [result.title, result.url, `取得日: ${today()}`, "", body].join("\n");
};

const render = () => {
  const value = build();
  els.output.value = value;
  const chars = [...value].length.toLocaleString("ja-JP");
  els.meta.textContent = `${chars} 文字${result && result.truncated ? "（長すぎるため途中まで）" : ""}`;
};

// ファイル名に使えない文字・制御文字を除く
const safeFileName = (s, ext) => {
  const base = (s || "page")
    .replace(/[\u0000-\u001f\u007f<>:"/\\|?*]/g, " ")
    .replace(/^[\s.]+|[\s.]+$/g, "")
    .replace(/\s+/g, " ")
    .slice(0, 80) || "page";
  return `${base}.${ext}`;
};

// 戻り値をそのまま信用せず、型と長さを確認する
const validate = (r) => {
  if (!r || typeof r !== "object") return null;
  const str = (v, max) => (typeof v === "string" ? v.slice(0, max) : "");
  return {
    title: str(r.title, 300),
    url: str(r.url, 4000),
    text: str(r.text, 300000),
    markdown: str(r.markdown, 400000),
    truncated: r.truncated === true,
  };
};

async function extract() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || typeof tab.id !== "number") return fail("タブが見つかりません。");

  let scheme = "";
  try {
    scheme = new URL(tab.url || "").protocol;
  } catch {
    /* URL が読めないページ */
  }
  if (scheme !== "http:" && scheme !== "https:" && scheme !== "file:") {
    return fail("このページ（Chrome の設定画面や拡張機能ストアなど）では使えません。");
  }

  let injected;
  try {
    injected = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, // メインフレームのみ。埋め込み広告などの iframe は読まない
      files: ["extractor.js"],
      // world は既定の ISOLATED（ページの JS から干渉されない）
    });
  } catch (e) {
    const msg = String((e && e.message) || e);
    if (scheme === "file:") {
      return fail("ローカルファイルで使うには、拡張機能の詳細で「ファイルの URL へのアクセスを許可する」をオンにしてください。");
    }
    return fail(`このページでは実行できませんでした（${msg.slice(0, 200)}）。`);
  }

  result = validate(injected && injected[0] && injected[0].result);
  if (!result || !(result.text || result.markdown)) return fail("本文が見つかりませんでした。");

  els.title.textContent = result.title || "（タイトルなし）";
  els.title.title = result.title;
  render();
  els.copy.disabled = false;
  els.save.disabled = false;
  setStatus("");
}

els.copy.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(build());
    setStatus("コピーしました。");
  } catch {
    // クリップボード API が使えないときは選択だけしておく
    els.output.focus();
    els.output.select();
    setStatus("コピーできませんでした。選択状態にしたので Ctrl+C / ⌘+C でコピーしてください。", true);
  }
});

els.save.addEventListener("click", () => {
  const md = format() === "markdown";
  const blob = new Blob([build()], { type: md ? "text/markdown;charset=utf-8" : "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = safeFileName(result && result.title, md ? "md" : "txt");
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  setStatus("ダウンロードフォルダに保存しました。");
});

for (const r of document.querySelectorAll("input[name=format]")) r.addEventListener("change", render);
els.withSource.addEventListener("change", render);

extract().catch((e) => fail(`エラーが発生しました（${String((e && e.message) || e).slice(0, 200)}）。`));
