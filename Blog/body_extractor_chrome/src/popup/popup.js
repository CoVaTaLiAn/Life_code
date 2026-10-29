const $ = (id) => document.getElementById(id);
let result = null;

const METHOD_LABEL = {
  readability: "本文を自動抽出",
  selection: "選択範囲のみ",
  fallback: "本文を特定できず、ページ全体から抽出",
};

function currentFormat() {
  return document.querySelector('input[name="fmt"]:checked').value;
}

function buildOutput() {
  if (!result) return "";
  const md = currentFormat() === "markdown";
  const body = md ? result.markdown : result.text;
  if (!$("withHeader").checked) return body;
  const header = md
    ? `# ${result.title}\n\n<${result.url}>\n\n`
    : `${result.title}\n${result.url}\n\n`;
  return header + body;
}

function render() {
  $("output").value = buildOutput();
}

function flash(msg) {
  $("status").textContent = msg;
  clearTimeout(flash.t);
  flash.t = setTimeout(() => { $("status").textContent = ""; }, 2000);
}

function safeFileName(s) {
  return (s || "page").replace(/[\\/:*?"<>|\n\r\t]/g, "_").trim().slice(0, 80) || "page";
}

async function extract() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["lib/Readability.js", "content/extract.js"],
    });
    result = res.result;
  } catch (e) {
    // chrome:// やウェブストアなど、拡張が入れないページ
    $("title").textContent = "このページでは使えません";
    $("meta").textContent = "Chromeの設定画面や拡張機能ストアなどは対象外です。";
    $("copy").disabled = $("save").disabled = true;
    return;
  }

  $("title").textContent = result.title || "(タイトルなし)";
  $("title").title = result.title;
  const meta = [METHOD_LABEL[result.method], `${result.length.toLocaleString()}文字`];
  if (result.siteName) meta.push(result.siteName);
  if (result.byline) meta.push(result.byline);
  $("meta").textContent = meta.join(" ・ ");
  render();
}

$("copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("output").value);
  flash("コピーしました");
});

$("save").addEventListener("click", () => {
  const md = currentFormat() === "markdown";
  const blob = new Blob([$("output").value], { type: md ? "text/markdown" : "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${safeFileName(result && result.title)}.${md ? "md" : "txt"}`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  flash("保存しました");
});

document.querySelectorAll('input[name="fmt"], #withHeader').forEach((el) => {
  el.addEventListener("change", render);
});

extract();
