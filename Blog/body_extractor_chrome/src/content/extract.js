// ページに注入され、本文を抽出して結果を返す。
// 直前に lib/Readability.js が注入されている前提。
// 最後に評価された式の値が executeScript の結果になる。
(() => {
  const BLOCK = new Set([
    "P", "DIV", "SECTION", "ARTICLE", "HEADER", "FOOTER", "MAIN", "ASIDE",
    "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "BLOCKQUOTE",
    "PRE", "TABLE", "TR", "FIGURE", "FIGCAPTION", "HR", "DL", "DT", "DD",
  ]);

  // 連続空行をまとめ、前後の空白を整える
  const tidy = (s) =>
    s
      .replace(/[ \t ]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();

  // ---- プレーンテキスト化 ----
  function toText(root) {
    let out = "";
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        out += node.textContent.replace(/\s+/g, " ");
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.tagName;
      if (tag === "BR") { out += "\n"; return; }
      if (tag === "PRE") { out += "\n\n" + node.textContent + "\n\n"; return; }
      if (tag === "LI") {
        out += "\n・";
        node.childNodes.forEach(walk);
        out += "\n";
        return;
      }
      const block = BLOCK.has(tag);
      if (block) out += "\n\n";
      node.childNodes.forEach(walk);
      if (tag === "TD" || tag === "TH") out += "\t";
      if (block) out += "\n\n";
    };
    walk(root);
    return tidy(out.replace(/\n[ \t]+/g, "\n").replace(/\n+(・)/g, "\n$1"));
  }

  // ---- Markdown化 ----
  function toMarkdown(root, baseUrl) {
    const abs = (u) => {
      try { return new URL(u, baseUrl).href; } catch { return u; }
    };
    const inline = (node) => {
      let s = "";
      node.childNodes.forEach((c) => { s += md(c, 0); });
      return s;
    };
    const md = (node, depth) => {
      if (node.nodeType === Node.TEXT_NODE) {
        return node.textContent.replace(/\s+/g, " ");
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return "";
      const tag = node.tagName;
      switch (tag) {
        case "H1": case "H2": case "H3": case "H4": case "H5": case "H6":
          return `\n\n${"#".repeat(+tag[1])} ${inline(node).trim()}\n\n`;
        case "P":
          return `\n\n${inline(node).trim()}\n\n`;
        case "BR":
          return "  \n";
        case "HR":
          return "\n\n---\n\n";
        case "STRONG": case "B": {
          const t = inline(node).trim();
          return t ? `**${t}**` : "";
        }
        case "EM": case "I": {
          const t = inline(node).trim();
          return t ? `*${t}*` : "";
        }
        case "CODE":
          return "`" + node.textContent + "`";
        case "PRE":
          return "\n\n```\n" + node.textContent.replace(/\n$/, "") + "\n```\n\n";
        case "A": {
          const t = inline(node).trim();
          const href = node.getAttribute("href");
          if (!href || href.startsWith("#") || !t) return t;
          return `[${t}](${abs(href)})`;
        }
        case "IMG": {
          const src = node.getAttribute("src");
          return src ? `![${node.getAttribute("alt") || ""}](${abs(src)})` : "";
        }
        case "BLOCKQUOTE": {
          const body = tidy(inline(node));
          return "\n\n" + body.split("\n").map((l) => "> " + l).join("\n") + "\n\n";
        }
        case "UL": case "OL": {
          let i = 0;
          let s = "\n";
          node.childNodes.forEach((li) => {
            if (li.nodeType !== Node.ELEMENT_NODE || li.tagName !== "LI") return;
            i++;
            const mark = tag === "OL" ? `${i}.` : "-";
            let content = "";
            li.childNodes.forEach((c) => {
              content += (c.tagName === "UL" || c.tagName === "OL") ? md(c, depth + 1) : md(c, depth);
            });
            s += `${"  ".repeat(depth)}${mark} ${tidy(content)}\n`;
          });
          return depth === 0 ? s + "\n" : s;
        }
        case "TR": {
          const cells = [...node.children].map((c) => inline(c).trim().replace(/\|/g, "\\|"));
          return "| " + cells.join(" | ") + " |\n";
        }
        case "TABLE": {
          const rows = [...node.querySelectorAll("tr")];
          if (!rows.length) return "";
          let s = "\n\n";
          rows.forEach((r, idx) => {
            s += md(r, depth);
            if (idx === 0) s += "|" + " --- |".repeat(r.children.length) + "\n";
          });
          return s + "\n";
        }
        default: {
          const t = inline(node);
          return BLOCK.has(tag) ? `\n\n${t}\n\n` : t;
        }
      }
    };
    return tidy(md(root, 0).replace(/\n[ \t]+(?![ \t]*[-\d])/g, "\n"));
  }

  // ---- メイン ----
  const url = location.href;
  let title = document.title;
  let byline = "";
  let siteName = "";
  let root = null;
  let method = "readability";

  // 選択範囲があればそれを優先
  const sel = window.getSelection();
  if (sel && !sel.isCollapsed && sel.toString().trim().length > 0) {
    root = document.createElement("div");
    for (let i = 0; i < sel.rangeCount; i++) {
      root.appendChild(sel.getRangeAt(i).cloneContents());
    }
    method = "selection";
  } else {
    try {
      const article = new Readability(document.cloneNode(true)).parse();
      if (article && article.content) {
        title = article.title || title;
        byline = article.byline || "";
        siteName = article.siteName || "";
        root = new DOMParser().parseFromString(article.content, "text/html").body;
      }
    } catch (e) {
      console.warn("[本文だけコピー] Readability失敗:", e);
    }
    if (!root) {
      // 抽出できないページは body 全体のテキストで代用
      root = document.body.cloneNode(true);
      root.querySelectorAll("script,style,noscript,nav,header,footer,aside").forEach((n) => n.remove());
      method = "fallback";
    }
  }

  const text = toText(root);
  return {
    title,
    byline,
    siteName,
    url,
    method,
    text,
    markdown: toMarkdown(root, url),
    length: text.replace(/\s/g, "").length,
  };
})();
