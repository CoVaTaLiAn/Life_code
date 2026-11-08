// ページに注入して本文を取り出すスクリプト。
// - 拡張機能の「隔離された環境（ISOLATED world）」で動くので、ページ側の JS から関数を差し替えられない。
// - ページの DOM は読むだけで、書き換えない。
// - 返すのは文字列だけ（HTML は返さない）。ポップアップ側で HTML として解釈されることがないようにするため。
// - 画面に見えていない要素は読まない。隠し文字（プロンプトインジェクション等）を拾わないため。
// ファイルの最後の式の値が executeScript の戻り値になる。
(() => {
  const MAX_CHARS = 300000; // 巨大ページで固まらないための上限
  const MAX_NODES = 50000;

  const SKIP_TAGS = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS", "IFRAME", "FRAME",
    "OBJECT", "EMBED", "VIDEO", "AUDIO", "MAP", "FORM", "BUTTON", "INPUT", "SELECT",
    "TEXTAREA", "OPTION", "NAV", "ASIDE", "FOOTER", "DIALOG", "MENU", "LINK", "META",
  ]);
  const SKIP_ROLES = new Set([
    "navigation", "banner", "contentinfo", "complementary", "search", "menu",
    "menubar", "dialog", "alertdialog", "toolbar", "tablist",
  ]);
  // 本文ではなさそうな class / id（日本語サイトでよく見るものも含む）
  const NEGATIVE = /(^|[-_\s])(nav|navi|navbar|menu|breadcrumbs?|sidebar|side|widget|footer|header|masthead|comments?|reply|share|sns|social|related|recommend|ranking|pickup|popular|ads?|advert|advertisement|sponsor|promo|banner|cookie|consent|modal|popup|newsletter|subscribe|signup|login|pagination|pager|toc|tags?)([-_\s]|$)/i;
  const BLOCK_TAGS = new Set([
    "P", "DIV", "SECTION", "ARTICLE", "MAIN", "HEADER", "H1", "H2", "H3", "H4", "H5", "H6",
    "UL", "OL", "LI", "DL", "DT", "DD", "BLOCKQUOTE", "PRE", "TABLE", "THEAD", "TBODY",
    "TR", "FIGURE", "FIGCAPTION", "HR", "ADDRESS", "DETAILS", "SUMMARY",
  ]);

  const isVisible = (el) => {
    if (typeof el.checkVisibility === "function") {
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    } else {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
    }
    if (el.hidden || el.getAttribute("aria-hidden") === "true") return false;
    // 1px 以下に縮めて隠す・画面外に飛ばすタイプの隠し要素
    const r = el.getBoundingClientRect();
    if (r.width <= 1 && r.height <= 1 && el.childElementCount === 0) return false;
    if (r.right < -1000 || r.bottom < -1000) return false;
    return true;
  };

  const looksLikeBoilerplate = (el) => {
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (SKIP_ROLES.has(role)) return true;
    const hint = `${el.id || ""} ${typeof el.className === "string" ? el.className : ""}`;
    return NEGATIVE.test(hint);
  };

  const textLen = (el) => (el.textContent || "").replace(/\s+/g, "").length;

  // ---- 1. 本文の入れ物を探す ----
  const pickCandidate = () => {
    const articles = [...document.querySelectorAll("article")].filter(
      (a) => isVisible(a) && textLen(a) > 200
    );
    if (articles.length === 1) return articles[0];

    const main = document.querySelector("main, [role='main']");
    if (main && isVisible(main) && textLen(main) > 200 && articles.length === 0) return main;

    // 段落の文字数と句読点から親要素に点数を付ける（Readability 方式の簡易版）
    const scores = new Map();
    const paras = document.querySelectorAll("p, pre, blockquote, li, td, div > br");
    let count = 0;
    for (const raw of paras) {
      if (++count > MAX_NODES) break;
      const p = raw.tagName === "BR" ? raw.parentElement : raw;
      const len = textLen(p);
      if (len < 25) continue;
      const commas = ((p.textContent || "").match(/[,、，。.]/g) || []).length;
      const score = 1 + Math.min(commas, 10) + Math.min(len / 100, 3);
      let node = p.parentElement;
      for (let depth = 0; node && node !== document.documentElement && depth < 3; depth++) {
        if (!looksLikeBoilerplate(node)) {
          scores.set(node, (scores.get(node) || 0) + score / (depth + 1));
        }
        node = node.parentElement;
      }
    }

    let best = null;
    let bestScore = 0;
    for (const [el, s] of scores) {
      // リンクだらけの要素（メニュー等）は減点
      const linkLen = [...el.querySelectorAll("a")].reduce((n, a) => n + textLen(a), 0);
      const density = linkLen / Math.max(textLen(el), 1);
      const adjusted = s * (1 - Math.min(density, 0.9));
      if (adjusted > bestScore && isVisible(el)) {
        best = el;
        bestScore = adjusted;
      }
    }
    return best || main || document.body;
  };

  // ---- 2. 文字列にする（text と markdown の 2 種類） ----
  const safeUrl = (href) => {
    try {
      const u = new URL(href, location.href);
      // javascript: や data: などは出力しない
      if (u.protocol !== "http:" && u.protocol !== "https:") return null;
      return u.href;
    } catch {
      return null;
    }
  };
  const mdEscape = (s) => s.replace(/([\\`*_[\]<>|])/g, "\\$1");
  const mdUrl = (s) => s.replace(/[()\s<>]/g, (c) => encodeURIComponent(c));

  const serialize = (root, markdown) => {
    let out = "";
    let nodes = 0;
    const listStack = [];

    // 末尾の改行を n 個にそろえる（文字列全体を正規表現で走査しないよう末尾だけ見る）
    const newline = (n = 1) => {
      let end = out.length;
      while (end > 0 && (out[end - 1] === " " || out[end - 1] === "\t")) end--;
      if (end !== out.length) out = out.slice(0, end);
      let have = 0;
      while (have < out.length && out[out.length - 1 - have] === "\n") have++;
      if (out.length && have < n) out += "\n".repeat(n - have);
    };

    const walk = (node, inPre, quote) => {
      if (out.length > MAX_CHARS || ++nodes > MAX_NODES) return;

      if (node.nodeType === Node.TEXT_NODE) {
        let t = node.nodeValue || "";
        if (!inPre) t = t.replace(/\s+/g, " ");
        if (!t) return;
        const atLineStart = !out.length || out.endsWith("\n");
        if (!inPre && atLineStart && t.startsWith(" ")) t = t.slice(1);
        if (markdown && !inPre) t = mdEscape(t);
        if (markdown && quote && atLineStart && t) out += "> ";
        out += t;
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;

      const el = node;
      const tag = el.tagName;
      if (SKIP_TAGS.has(tag)) return;
      if (el !== root && looksLikeBoilerplate(el)) return;
      if (!isVisible(el)) return;

      const kids = () => {
        for (const c of el.childNodes) walk(c, inPre || tag === "PRE", quote || tag === "BLOCKQUOTE");
        // Shadow DOM（open のもの）も読む
        if (el.shadowRoot) for (const c of el.shadowRoot.childNodes) walk(c, inPre, quote);
      };

      if (tag === "BR") { out += "\n"; return; }
      if (tag === "HR") { newline(2); if (markdown) out += "---"; newline(2); return; }
      if (tag === "IMG") {
        const alt = (el.getAttribute("alt") || "").trim();
        if (markdown && alt) out += `[画像: ${mdEscape(alt)}]`;
        return;
      }

      const h = /^H([1-6])$/.exec(tag);
      if (h) {
        newline(2);
        if (markdown) out += "#".repeat(Number(h[1])) + " ";
        kids();
        newline(2);
        return;
      }
      if (tag === "PRE") {
        newline(2);
        if (markdown) out += "```\n";
        kids();
        if (markdown) { newline(1); out += "```"; }
        newline(2);
        return;
      }
      if (tag === "UL" || tag === "OL") {
        newline(listStack.length ? 1 : 2);
        listStack.push({ ordered: tag === "OL", n: 0 });
        kids();
        listStack.pop();
        newline(listStack.length ? 1 : 2);
        return;
      }
      if (tag === "LI") {
        newline(1);
        const top = listStack[listStack.length - 1];
        const indent = "  ".repeat(Math.max(listStack.length - 1, 0));
        out += indent + (top && top.ordered ? `${++top.n}. ` : markdown ? "- " : "・");
        kids();
        newline(1);
        return;
      }
      if (tag === "A" && markdown) {
        const url = safeUrl(el.getAttribute("href") || "");
        const before = out.length;
        kids();
        const label = out.slice(before).trim();
        if (url && label && !label.includes("\n")) {
          out = out.slice(0, before) + `[${label}](${mdUrl(url)})`;
        }
        return;
      }
      const wrap = (mark) => {
        const before = out.length;
        kids();
        const inner = out.slice(before);
        // 中身が空・改行をまたぐ場合は記号を付けない
        if (inner.trim() && !inner.includes("\n")) out = out.slice(0, before) + mark + inner.trim() + mark;
      };
      if (markdown && (tag === "STRONG" || tag === "B")) { wrap("**"); return; }
      if (markdown && (tag === "EM" || tag === "I")) { wrap("*"); return; }
      if (markdown && tag === "CODE" && !inPre) { wrap("`"); return; }
      if (tag === "TD" || tag === "TH") { kids(); out += markdown ? " | " : "\t"; return; }
      if (tag === "TR") { newline(1); if (markdown) out += "| "; kids(); newline(1); return; }

      if (BLOCK_TAGS.has(tag)) {
        newline(tag === "P" || tag === "BLOCKQUOTE" ? 2 : 1);
        kids();
        newline(tag === "P" || tag === "BLOCKQUOTE" ? 2 : 1);
        return;
      }
      kids();
    };

    walk(root, false, false);
    return out
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim()
      .slice(0, MAX_CHARS);
  };

  // 共有時に余計な情報を残さないよう、計測用パラメータと # 以降を消した URL
  const cleanUrl = () => {
    try {
      const u = new URL(location.href);
      u.hash = "";
      for (const k of [...u.searchParams.keys()]) {
        if (/^(utm_|fbclid$|gclid$|yclid$|mc_|_ga$|igshid$|ref_src$)/i.test(k)) u.searchParams.delete(k);
      }
      return u.href;
    } catch {
      return "";
    }
  };

  const root = pickCandidate();
  const h1 = root.querySelector("h1") || document.querySelector("h1");
  const title = ((document.title || "") || (h1 ? h1.textContent : "")).replace(/\s+/g, " ").trim().slice(0, 300);

  const text = serialize(root, false);
  const markdown = serialize(root, true);

  return {
    title: String(title),
    url: String(cleanUrl()),
    text: String(text),
    markdown: String(markdown),
    truncated: text.length >= MAX_CHARS,
  };
})();
