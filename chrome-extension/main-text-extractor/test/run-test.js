// 使い方: node test/run-test.js   （Playwright が入っている環境で実行）
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const extDir = path.resolve(__dirname, "..");
const code = fs.readFileSync(path.join(extDir, "extractor.js"), "utf8");

let failed = 0;
const check = (name, ok) => {
  console.log(`${ok ? "OK  " : "FAIL"} ${name}`);
  if (!ok) failed++;
};

(async () => {
  // 1) 抽出ロジックをテストページで確認
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto("file://" + path.join(__dirname, "fixture.html") + "?utm_source=x&id=7#top");
  const r = await page.evaluate(code);
  await browser.close();

  console.log("----- text -----\n" + r.text + "\n----- markdown -----\n" + r.markdown + "\n----------------");
  check("タイトル", r.title === "テスト記事 | サンプルニュース");
  check("URL から utm_ と # を除去", r.url.endsWith("fixture.html?id=7"));
  for (const s of ["最初の段落", "小見出し", "項目その二", "引用された文章", "console.log(x);", "最後の段落"]) {
    check(`本文を含む: ${s}`, r.text.includes(s) && r.markdown.includes(s));
  }
  for (const s of ["政治", "隠し文字", "画面外", "スクリプトの文字", "シェア", "ランキング", "広告", "コメント", "©"]) {
    check(`含まない: ${s}`, !r.text.includes(s) && !r.markdown.includes(s));
  }
  check("Markdown: 安全なリンクは残す", r.markdown.includes("[安全なリンク](https://example.com/x?a=1)"));
  check("Markdown: javascript: リンクは URL を出さない", !r.markdown.includes("javascript:") && r.markdown.includes("危険なリンク"));
  check("Markdown: 見出し", r.markdown.includes("## 小見出し"));
  check("Markdown: 強調", r.markdown.includes("**強調**"));
  check("Markdown: コードブロック", r.markdown.includes("```\nconst x = 1;"));
  check("Markdown: 引用", r.markdown.includes("> 引用された文章"));
  check("テキスト: 箇条書き", r.text.includes("・項目その一"));

  // 2) 拡張機能として読み込めるか（manifest・CSP のエラーがないか）
  const id = [...crypto.createHash("sha256").update(extDir).digest("hex").slice(0, 32)]
    .map((c) => String.fromCharCode(97 + parseInt(c, 16)))
    .join("");
  const ctx = await chromium.launchPersistentContext("", {
    headless: true,
    channel: "chromium", // 拡張機能を headless で読み込むのに必要
    args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`],
  });
  const p = await ctx.newPage();
  const errors = [];
  p.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  p.on("pageerror", (e) => errors.push(String(e)));
  await p.goto(`chrome-extension://${id}/popup.html`);
  await p.waitForTimeout(500);
  const h1 = await p.textContent("#title");
  // ポップアップとして開いていないのでタブ取得は失敗するのが正しい。ここでは画面が描画され、CSP 違反がないことだけ見る
  check("ポップアップが表示される", typeof h1 === "string" && h1.length > 0);
  check("CSP 違反がない", !errors.some((e) => /Content Security Policy/i.test(e)));
  if (errors.length) console.log("console errors:", errors);
  await p.screenshot({ path: path.join(__dirname, "popup.png") });
  await ctx.close();

  console.log(failed ? `\n${failed} 件失敗` : "\nすべて成功");
  process.exit(failed ? 1 : 0);
})();
