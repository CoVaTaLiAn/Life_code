/**
 * Gmail 自動振り分け + 毎朝の要約メール（Google Apps Script）
 *
 * 判定は4段階（トークンを使うのは迷ったものだけ）：
 *   1. ルール（送信元・キーワード、あなたが過去に決めた送信元）… 無料
 *   2. ルールで決まらないものは確率を出す（Jev。キー未設定なら過去の判定から学ぶ簡易計算）
 *      スパム・既読でよい確率がとても高いものだけ自動で処理する
 *   3. 残りは「要判断」ラベルを付け、シート「判断待ち」に載せる。
 *      Claude Code で「Gmailの判断待ちを見て」と頼むと、Claude が提案を書き込む
 *   4. あなたが決める（シートの「あなたの判断」列、または Gmail でラベルを付ける）
 *      → 1時間以内に処理し、その送信元を覚えて次からルールで自動処理する
 * 判定結果はすべてスプレッドシート「Gmail振り分けログ」に残る。
 * 使い方は同じフォルダの README.md を参照。
 */

// ===== 設定（ここを編集すれば振り分けルールを変えられる） =====

const CONFIG = {
  // 要約メールの送り先（空なら自分宛て）
  summaryTo: '',
  // 要約を送る時刻（0-23時）
  summaryHour: 7,
  // 1回の実行で処理する最大スレッド数
  maxThreads: 100,

  labels: {
    pick: '転職/注目',
    jobOther: '転職/その他',
    ad: '広告',
    notice: '通知',
    check: '要確認',
    reply: '要返信',
    keep: '残す',
    ask: '要判断',
  },

  // ルールで決まらないメールの確率判定
  prob: {
    autoThreshold: 0.95, // これ以上ならあなたに聞かずに処理（スパム→迷惑メール、既読でよい→既読）
    minExamples: 10, // 簡易計算：この件数以上の学習例がある種類だけ自動処理に使う
    trainRows: 3000, // 簡易計算：ログの直近何行から学ぶか
  },

  // Jev（TypeSafe AI）。スクリプト プロパティ TYPESAFE_API_KEY を登録したときだけ使う
  jev: {
    url: 'https://api.typesafe.ai/v1/systemone',
    model: 'jev-latest',
    maxPerRun: 20, // 1回の実行で Jev に回す上限（費用の暴走防止）
    bodyChars: 300, // Jev に渡す本文の文字数
  },

  // Jev・Claude に伝える判断基準（Obsidian「輝く環境.md」より）
  profile: [
    '受信者はデータサイエンティスト志望の転職活動中の人。',
    '注目すべき求人：データサイエンス・データ分析・ヘルスケアIT・医療・ゲノム領域、年収480万円以上、横浜から通勤90分以内、事業に嘘がない会社。',
    '避けたい求人：営業職、未経験歓迎の大量採用、根性論の社風、事業内容が怪しいもの。',
  ].join('\n'),

  // 転職サイト・エージェント（このどれかから来たら転職メール）
  jobSenders: [
    'bizreach.co.jp', 'doda.jp', 'direct-doda.jp', 'dm-doda.jp', 'persol.co.jp',
    'jac-recruitment.jp', 'openwork.jp', 'signate.jp', 'green-japan.com',
    'en-japan.com', 'r-agent.com', 'mynavi.jp', 'type.jp', 'wantedly.com',
  ],

  // 転職メールのうち、件名か本文冒頭にこれがあれば「注目」
  pickKeywords: [
    'データサイエンティスト', 'データサイエンス', 'データ分析', 'データアナリスト',
    '機械学習', 'AI', 'ヘルスケア', '医療', 'メディカル', 'ライフサイエンス',
    'ゲノム', '臨床', '面談確約', '公募',
    '野村総合研究所', 'SOMPO', 'メディア情報システム', 'GenMine', 'ビー・エム・エル',
    'エムスリー', 'シンクデータ',
  ],

  // 注目キーワードがあってもこれがあれば「その他」に落とす
  dropKeywords: [
    '未経験', '同期10名', '看護師', '医療事務', '営業職', '医療機器営業',
    '職務経歴書の書き方', '求人の探し方', '面談で話すべきこと', 'アンケート',
  ],

  // 広告として既読アーカイブする送信元
  adSenders: [
    'audible.co.jp', 'amazon.co.jp', 'amazonmusic.com', 'xmind.ai',
    'marketing.', 'newsletter', 'news@', 'store-news@',
  ],

  // 明らかなスパム：件名にこれがあれば迷惑メールへ
  spamKeywords: [
    '当選しました', '当選のお知らせ', '高額当選', '受け取り待ち', '未受取の',
    '副業で月', '誰でも稼げる', '高収入確定', 'お金配り', '必ず儲かる', '元本保証',
    '出会い', 'セフレ', '人妻', 'バイアグラ',
    'アカウントが停止されました', 'アカウントを一時停止', 'お支払い情報を更新してください',
  ],
  // 明らかなスパム：送信元にこれが含まれれば迷惑メールへ（怪しいドメイン）
  spamSenders: ['.xyz>', '.top>', '.click>', '.icu>', '.buzz>', '.rest>', '.cfd>', '.sbs>'],

  // 既読にしてゴミ箱へ移す送信元（30日でGmailが完全に削除する）
  trashSenders: ['contract-one.com'],

  // 既読だけにして受信箱に残す送信元（領収書・自動タスク通知など）
  noticeSenders: ['tm.openai.com', 'invoice@', 'mail.anthropic.com', 'linkedin.com', 'notifications@github.com'],

  // 件名にこれがあれば関係ないお知らせとして既読（受信箱に残す）。送信元を覚えたもの・セキュリティ系が優先
  noticeKeywords: [
    '利用規約', 'プライバシーポリシー', '規約改定', '規約の改定', 'メンテナンスのお知らせ',
    'サービス終了', '仕様変更', 'ポイント失効', 'ポイントのお知らせ', 'ご利用明細',
    'Terms of Service', 'Privacy Policy', 'policy update',
  ],

  // 未読のまま残して要約で知らせる（セキュリティ系）
  checkKeywords: [
    'Security alert', 'セキュリティ', 'new device', 'ログイン', 'shared some Google Account data',
    'パスワード', '不正',
  ],
};

// あなたが付けられるカテゴリ（「要判断」以外）。spam・trash はシートでだけ選べる
const KINDS = ['pick', 'jobOther', 'ad', 'notice', 'check', 'reply', 'keep'];
const SPAM_NAME = '迷惑メール';
const TRASH_NAME = '削除';

// 確率の3グループ（カテゴリ名 → グループ）
const GROUP_OF = {
  迷惑メール: 'spam',
  '転職/その他': 'readOnly', 広告: 'readOnly', 通知: 'readOnly', 削除: 'readOnly',
  '転職/注目': 'important', 要確認: 'important', 要返信: 'important', 残す: 'important',
};

// 判断待ちシートの列
const ASK_SHEET = '判断待ち';
const ASK_HEADER = ['ID', '受信日時', '差出人', '件名', '冒頭', 'スパム確率', '既読でよい確率', '確率の出どころ',
  'Claudeの提案', 'Claudeの理由', 'あなたの判断', '処理済み', 'リンク'];
const COL = { id: 0, suggest: 8, reason: 9, decision: 10, done: 11 };

// ===== 初回だけ手動で実行する =====

function setup() {
  Object.values(CONFIG.labels).forEach(getOrCreateLabel_);
  shareSheet_(getSpreadsheet_());
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sortInbox').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('sendSummary').timeBased().everyDays(1).atHour(CONFIG.summaryHour).create();
  sortInbox();
}

// ===== 1時間ごと：振り分け =====

function sortInbox() {
  const L = {};
  Object.entries(CONFIG.labels).forEach(([k, name]) => (L[k] = getOrCreateLabel_(name)));
  const props = PropertiesService.getScriptProperties();
  const ss = getSpreadsheet_();
  const log = loadLog_();
  const learned = loadLearned_();
  const state = { changed: false };
  const rows = [];

  // 先にあなたの判断を反映する（Gmail のラベル → シートの「あなたの判断」列）
  const answered = learnFromUser_(L, learned, state, log, rows);
  applySheetDecisions_(ss, L, learned, state, log, rows, answered);
  if (state.changed) props.setProperty('LEARNED', JSON.stringify(learned));

  const threads = GmailApp.search('in:inbox is:unread has:nouserlabels', 0, CONFIG.maxThreads);
  const jevKey = props.getProperty('TYPESAFE_API_KEY');
  const pct = x => Math.round(x * 100) + '%';
  let model = null; // 簡易計算のモデル。必要になったときだけ作る
  let jevCalls = 0;
  const askRows = [];

  threads.forEach(thread => {
    const msg = thread.getMessages().slice(-1)[0];
    const fromRaw = msg.getFrom();
    const subject = msg.getSubject() || '';
    const body = msg.getPlainBody();
    let kind = classify_(fromRaw.toLowerCase(), subject, subject + ' ' + body.slice(0, 1500), learned);
    let by = 'ルール';
    let reason = '';

    if (kind === 'summary') {
      thread.addLabel(L.notice); // 自分の要約メールは未読のまま「通知」に入れるだけ
      return;
    }

    if (kind === 'none') {
      // 迷ったものだけ確率を出す。Jev が使えなければ簡易計算
      let p = null;
      if (jevKey && jevCalls < CONFIG.jev.maxPerRun) {
        jevCalls++;
        p = scoreWithJev_(jevKey, fromRaw, subject, body);
      }
      if (!p) {
        model = model || buildModel_(ss);
        p = scoreLocal_(model, fromRaw, subject);
      }
      by = p.source;
      const t = CONFIG.prob.autoThreshold;
      if (p.trusted.spam && p.spam >= t) {
        kind = 'spam';
        reason = 'スパム確率 ' + pct(p.spam);
      } else if (p.trusted.readOnly && p.readOnly >= t) {
        kind = 'notice';
        reason = '既読でよい確率 ' + pct(p.readOnly);
      } else {
        kind = 'ask';
        reason = 'スパム ' + pct(p.spam) + '・既読でよい ' + pct(p.readOnly) + '（' + p.source + '）';
        askRows.push([thread.getId(), msg.getDate(), fromRaw, subject, body.replace(/\s+/g, ' ').trim().slice(0, 100),
          round2_(p.spam), round2_(p.readOnly), p.source, '', '', '', '', threadLink_(thread.getId())]);
      }
    }

    rows.push(logRow_(by, kind, reason, fromRaw, subject, thread));
    applyKind_(thread, kind, L, log, { s: subject, f: shortFrom_(fromRaw), id: thread.getId(), r: reason });
  });

  appendAskRows_(ss, askRows);
  appendToSheet_(ss, rows);
  saveLog_(log);
}

// 決まったカテゴリに応じてラベル付け・既読・アーカイブする
function applyKind_(thread, kind, L, log, item) {
  switch (kind) {
    case 'pick':
      thread.addLabel(L.pick);
      log.pick.push(item);
      break;
    case 'jobOther':
      thread.addLabel(L.jobOther).markRead().moveToArchive();
      log.counts.jobOther++;
      break;
    case 'ad':
      thread.addLabel(L.ad).markRead().moveToArchive();
      log.counts.ad++;
      break;
    case 'notice':
      thread.addLabel(L.notice).markRead();
      log.counts.notice++;
      break;
    case 'spam':
      thread.markRead().moveToSpam(); // Gmail の迷惑メールへ（30日で自動削除。間違いなら「迷惑メールではない」で戻せる）
      log.counts.spam++;
      break;
    case 'trash':
      thread.markRead().moveToTrash();
      log.counts.trash++;
      break;
    case 'check':
      thread.addLabel(L.check);
      log.check.push(item);
      break;
    case 'reply':
      thread.addLabel(L.reply);
      log.reply.push(item);
      break;
    case 'ask':
      thread.addLabel(L.ask); // 未読のまま受信箱に残し、あなたに聞く
      log.ask.push(item);
      break;
    default: // keep：受信箱に未読のまま残す。再判定しないようラベルだけ付ける
      thread.addLabel(L.keep);
      log.counts.keep++;
  }
}

// ===== あなたの判断を反映して覚える =====

// 「要判断」のメールにあなたが Gmail でカテゴリのラベルを付けていたら処理する。処理したスレッドIDを返す
function learnFromUser_(L, learned, state, log, rows) {
  const threads = GmailApp.search('label:' + CONFIG.labels.ask, 0, CONFIG.maxThreads);
  const done = new Set();

  threads.forEach(thread => {
    const names = thread.getLabels().map(l => l.getName());
    const kind = KINDS.find(k => names.includes(CONFIG.labels[k]));
    if (!kind) return; // まだ答えていない
    rememberAndApply_(thread, kind, 'Gmailで判断', L, learned, state, log, rows);
    done.add(thread.getId());
  });
  return done;
}

// シート「判断待ち」の「あなたの判断」列が埋まった行を処理する
function applySheetDecisions_(ss, L, learned, state, log, rows, answered) {
  const sh = ss.getSheetByName(ASK_SHEET);
  if (!sh || sh.getLastRow() < 2) return;
  const n = sh.getLastRow() - 1;
  const vals = sh.getRange(2, 1, n, ASK_HEADER.length).getValues();
  const doneCol = vals.map(r => [r[COL.done]]);
  let touched = false;

  vals.forEach((r, i) => {
    if (r[COL.done]) return;
    const id = String(r[COL.id]);
    const mark = v => { doneCol[i][0] = v; touched = true; };
    if (answered.has(id)) return mark('Gmailで回答');
    const decision = String(r[COL.decision] || '').trim();
    if (!decision) return; // まだ答えていない
    const kind = kindFromName_(decision);
    if (!kind) return mark('不明な判断: ' + decision);
    let thread = null;
    try { thread = GmailApp.getThreadById(id); } catch (e) { /* 削除済みなど */ }
    if (!thread) return mark('メールが見つからない');
    rememberAndApply_(thread, kind, 'シートで判断', L, learned, state, log, rows);
    mark(new Date());
  });

  if (touched) sh.getRange(2, COL.done + 1, n, 1).setValues(doneCol);
}

function rememberAndApply_(thread, kind, how, L, learned, state, log, rows) {
  const msg = thread.getMessages().slice(-1)[0];
  const addr = senderAddress_(msg.getFrom());
  learned[addr] = kind;
  state.changed = true;
  thread.removeLabel(L.ask);
  rows.push(logRow_('あなた', kind, how + '。次から ' + addr + ' は自動でこのカテゴリ', msg.getFrom(), msg.getSubject(), thread));
  applyKind_(thread, kind, L, log, { s: msg.getSubject() || '', f: shortFrom_(msg.getFrom()), id: thread.getId() });
}

// カテゴリ名（ラベル名・迷惑メール・削除）→ 内部の種類
function kindFromName_(name) {
  if (name === SPAM_NAME) return 'spam';
  if (name === TRASH_NAME) return 'trash';
  return KINDS.find(k => CONFIG.labels[k] === name) || null;
}

function kindName_(kind) {
  if (kind === 'spam') return SPAM_NAME;
  if (kind === 'trash') return TRASH_NAME;
  return CONFIG.labels[kind] || kind;
}

function loadLearned_() {
  const raw = PropertiesService.getScriptProperties().getProperty('LEARNED');
  return raw ? JSON.parse(raw) : {};
}

function senderAddress_(from) {
  const m = from.match(/<([^>]+)>/);
  return (m ? m[1] : from).trim().toLowerCase();
}

// ===== ルール判定 =====

function classify_(from, subject, text, learned) {
  // 送信元は小文字で比較、キーワードは大文字小文字を区別（"AI" が "mail" に当たらないように）
  const fromHas = list => list.some(k => from.includes(k.toLowerCase()));
  const has = (list, s) => list.some(k => s.includes(k));

  if (subject.startsWith('[Gmail要約]')) return 'summary';
  if (fromHas(CONFIG.trashSenders)) return 'trash';
  const addr = senderAddress_(from);
  if (learned && learned[addr]) return learned[addr];
  if (fromHas(CONFIG.spamSenders) || has(CONFIG.spamKeywords, subject)) return 'spam';
  if (fromHas(CONFIG.jobSenders)) {
    if (has(CONFIG.pickKeywords, text) && !has(CONFIG.dropKeywords, text)) return 'pick';
    return 'jobOther';
  }
  if (fromHas(CONFIG.noticeSenders)) return 'notice';
  if (has(CONFIG.checkKeywords, subject)) return 'check';
  if (fromHas(CONFIG.adSenders)) return 'ad';
  if (has(CONFIG.noticeKeywords, subject)) return 'notice';
  return 'none';
}

// ===== 確率判定（ルールに当たらないメールだけ） =====

// Jev（TypeSafe AI）に「スパムか」「既読でよいか」の確率を聞く。失敗したら null（簡易計算に切り替わる）
function scoreWithJev_(apiKey, from, subject, body) {
  const payload = {
    model: CONFIG.jev.model,
    state: ['差出人: ' + from, '件名: ' + subject, '本文冒頭: ' + body.replace(/\s+/g, ' ').slice(0, CONFIG.jev.bodyChars)].join('\n'),
    questions: {
      spam: {
        type: 'noul',
        instructions: 'このメールは明らかなスパムか？',
        criteria: {
          true: '詐欺・フィッシング・出会い系・怪しい儲け話・無差別に送られた迷惑メール',
          false: '実在の会社・サービス・人から受信者に届いた正規のメール（宣伝でも正規なら偽）',
        },
      },
      readOnly: {
        type: 'noul',
        instructions: CONFIG.profile + '\nこのメールは、この受信者にとって読まずに既読にしてよいか？',
        criteria: {
          true: '広告・宣伝・メルマガ・関係ないお知らせ・読むだけで済む自動通知',
          false: '本人の確認・返信・手続き・支払い・予約などの対応が要るもの、人から届いたもの、条件に合う求人',
        },
      },
    },
  };
  try {
    const res = UrlFetchApp.fetch(CONFIG.jev.url, {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + apiKey },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
    const text = res.getContentText();
    if (res.getResponseCode() !== 200) {
      console.warn('Jevエラー ' + res.getResponseCode() + ': ' + text.slice(0, 300));
      return null;
    }
    // 返答は { answers: { spam: { type: 'noul', noul: 0.93 }, ... } }（公式資料 docs.typesafe.ai/primitives/noul）
    const data = JSON.parse(text);
    const ans = data.answers || {};
    const noul = k => (ans[k] && typeof ans[k].noul === 'number' ? ans[k].noul : findProb_(data, k));
    const spam = noul('spam');
    const readOnly = noul('readOnly');
    if (spam === null || readOnly === null) {
      console.warn('Jevの返答から確率を読めない: ' + text.slice(0, 500));
      return null;
    }
    return { spam: spam, readOnly: readOnly, source: 'Jev', trusted: { spam: true, readOnly: true } };
  } catch (e) {
    console.warn('Jev呼び出し失敗: ' + e.message);
    return null;
  }
}

// 予備：返答の形が将来変わっても、質問名 key の確率（0〜1の数）を探して読めるようにしている
function findProb_(obj, key) {
  const isP = v => typeof v === 'number' && v >= 0 && v <= 1;
  const firstP = o => {
    if (isP(o)) return o;
    if (!o || typeof o !== 'object') return null;
    for (const f of ['probability', 'prob', 'p', 'value', 'true', 'score']) if (isP(o[f])) return o[f];
    for (const v of Object.values(o)) { const x = firstP(v); if (x !== null) return x; }
    return null;
  };
  const search = o => {
    if (!o || typeof o !== 'object') return null;
    if (Array.isArray(o)) {
      for (const v of o) {
        if (v && typeof v === 'object' && (v.name === key || v.id === key || v.question === key)) return firstP(v);
        const x = search(v); if (x !== null) return x;
      }
      return null;
    }
    if (key in o) return firstP(o[key]);
    for (const v of Object.values(o)) { const x = search(v); if (x !== null) return x; }
    return null;
  };
  return search(obj);
}

// Jev の動作確認用。GAS エディタでこの関数を実行し、「実行ログ」で返答を見る
function testJev() {
  const key = PropertiesService.getScriptProperties().getProperty('TYPESAFE_API_KEY');
  if (!key) throw new Error('スクリプト プロパティ TYPESAFE_API_KEY が未設定');
  const r = scoreWithJev_(key, '"Prize Center" <win@lucky-prize.xyz>', '【当選】iPhone が当たりました', '今すぐ受け取りはこちら。期限は本日中です。');
  console.log(r ? 'OK: ' + JSON.stringify(r) : '失敗。上のログの返答を見て findProb_ を直す');
}

// 簡易計算：ログに残った「ルール」と「あなた」の判定から学ぶ（ナイーブベイズ）。無料
function buildModel_(ss) {
  const G = ['spam', 'readOnly', 'important'];
  const m = { n: {}, f: {}, tot: {}, vocab: {}, V: 1 };
  G.forEach(g => { m.n[g] = 0; m.f[g] = {}; m.tot[g] = 0; });
  const sh = ss.getSheets()[0];
  const last = sh.getLastRow();
  if (last < 2) return m;
  const k = Math.min(CONFIG.prob.trainRows, last - 1);
  sh.getRange(last - k + 1, 1, k, 6).getValues().forEach(r => {
    const g = GROUP_OF[r[2]];
    if (!g || (r[1] !== 'ルール' && r[1] !== 'あなた')) return; // 確率で決めた行は学ばない（思い込みの強化を防ぐ）
    m.n[g]++;
    features_(String(r[4]), String(r[5])).forEach(t => {
      m.f[g][t] = (m.f[g][t] || 0) + 1;
      m.tot[g]++;
      m.vocab[t] = 1;
    });
  });
  m.V = Object.keys(m.vocab).length + 1;
  return m;
}

function scoreLocal_(m, from, subject) {
  const G = ['spam', 'readOnly', 'important'];
  const total = G.reduce((s, g) => s + m.n[g], 0);
  const feats = features_(from, subject).filter(t => m.vocab[t]); // どこにも出てこない特徴は無視
  const lp = {};
  G.forEach(g => {
    lp[g] = Math.log((m.n[g] + 1) / (total + 3));
    feats.forEach(t => { lp[g] += Math.log(((m.f[g][t] || 0) + 1) / (m.tot[g] + m.V)); });
  });
  const max = Math.max(...G.map(g => lp[g]));
  const e = {};
  let sum = 0;
  G.forEach(g => { e[g] = Math.exp(lp[g] - max); sum += e[g]; });
  const enough = g => m.n[g] >= CONFIG.prob.minExamples && m.n.important >= CONFIG.prob.minExamples;
  // 簡易計算は確率が極端に出やすいので、迷惑メールへの自動移動は過去にスパムだった送信ドメインに限る
  const dom = 'd:' + (senderAddress_(from).split('@')[1] || '');
  return {
    spam: e.spam / sum, readOnly: e.readOnly / sum, source: '簡易計算',
    trusted: { spam: enough('spam') && (m.f.spam[dom] || 0) > 0, readOnly: enough('readOnly') },
  };
}

// 送信元アドレス・ドメイン、件名の英単語と日本語2文字ずつ
function features_(from, subject) {
  const addr = senderAddress_(from);
  const t = ['a:' + addr, 'd:' + (addr.split('@')[1] || '')];
  const s = subject.toLowerCase();
  (s.match(/[a-z0-9]{2,}/g) || []).forEach(w => t.push('w:' + w));
  const ja = s.replace(/[\x00-\x7f]/g, ' ');
  for (let i = 0; i < ja.length - 1; i++) {
    const b = ja.substr(i, 2);
    if (!/\s/.test(b)) t.push('b:' + b);
  }
  return [...new Set(t)];
}

// ===== スプレッドシート（判定ログ・判断待ち） =====

function getSpreadsheet_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('SHEET_ID');
  if (id) return SpreadsheetApp.openById(id);
  // 名前にアカウントを入れる（複数の Gmail で使っても、Claude がどのシートか分かるように）
  const ss = SpreadsheetApp.create('Gmail振り分けログ（' + Session.getEffectiveUser().getEmail() + '）');
  ss.getSheets()[0].appendRow(['日時', '判定者', 'カテゴリ', '理由', '差出人', '件名', 'リンク']);
  props.setProperty('SHEET_ID', ss.getId());
  shareSheet_(ss);
  return ss;
}

// スクリプト プロパティ SHARE_WITH にメールアドレスがあれば、ログのシートを編集者として共有する
// （サブの Gmail で動かすとき、Claude をつないだメインのアカウントから判断待ちを読み書きできるように）
function shareSheet_(ss) {
  const to = PropertiesService.getScriptProperties().getProperty('SHARE_WITH');
  if (!to) return;
  if (!ss.getEditors().some(u => u.getEmail() === to)) ss.addEditor(to);
}

function logRow_(by, kind, reason, from, subject, thread) {
  return [new Date(), by, kindName_(kind), reason, from, subject || '', threadLink_(thread.getId())];
}

function appendToSheet_(ss, rows) {
  if (!rows.length) return;
  const sh = ss.getSheets()[0];
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
}

function appendAskRows_(ss, rows) {
  if (!rows.length) return;
  let sh = ss.getSheetByName(ASK_SHEET);
  if (!sh) {
    sh = ss.insertSheet(ASK_SHEET, ss.getSheets().length); // 判定ログ（1枚目）の後ろに作る
    sh.appendRow(ASK_HEADER);
    sh.setFrozenRows(1);
  }
  const start = sh.getLastRow() + 1;
  sh.getRange(start, 1, rows.length, ASK_HEADER.length).setValues(rows);
  // 「あなたの判断」は選択式にする
  const choices = KINDS.map(k => CONFIG.labels[k]).concat([SPAM_NAME, TRASH_NAME]);
  const rule = SpreadsheetApp.newDataValidation().requireValueInList(choices, true).setAllowInvalid(false).build();
  sh.getRange(start, COL.decision + 1, rows.length, 1).setDataValidation(rule);
}

// ===== 毎朝：要約メール =====

function sendSummary() {
  const log = loadLog_();
  const c = log.counts;
  const lines = [];
  const section = (title, list, withReason) => {
    lines.push('【' + title + '】' + list.length + '件');
    list.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）' + (withReason && m.r ? '\n  ' + m.r : '') + '\n  ' + threadLink_(m.id)));
    if (!list.length) lines.push('- なし');
    lines.push('');
  };

  // 今も「要判断」のまま残っているものだけを聞く
  const pending = GmailApp.search('label:' + CONFIG.labels.ask, 0, 50).map(t => t.getId());
  const ask = log.ask.filter(m => pending.includes(m.id));
  const sheetId = PropertiesService.getScriptProperties().getProperty('SHEET_ID');

  section('あなたの判断待ち', ask, true);
  if (ask.length) {
    lines.push('→ Claude Code で「Gmailの判断待ちを見て」と頼むと、Claude が提案を付けます。');
    lines.push('→ 決め方はどちらでも：シート「判断待ち」の「あなたの判断」列で選ぶ／Gmail でラベルを付ける');
    lines.push('  ' + KINDS.map(k => CONFIG.labels[k]).join(' / ') + '（シートでは ' + SPAM_NAME + ' / ' + TRASH_NAME + ' も選べる）');
    lines.push('  1時間以内に処理し、同じ送信元は次から自動で振り分けます。', '');
  }
  section('転職/注目', log.pick, false);
  section('要返信', log.reply, true);
  section('要確認', log.check, false);

  lines.push('【自動処理】',
    '- 転職/その他：' + c.jobOther + '件（既読・アーカイブ）',
    '- 広告：' + c.ad + '件（既読・アーカイブ）',
    '- 通知：' + c.notice + '件（既読）',
    '- 迷惑メール：' + c.spam + '件（既読・迷惑メールへ）',
    '- 削除：' + c.trash + '件（既読・ゴミ箱）',
    '- 残す：' + c.keep + '件（受信箱に未読のまま）');

  if (sheetId) lines.push('', '判定ログ・判断待ち: https://docs.google.com/spreadsheets/d/' + sheetId);

  const to = CONFIG.summaryTo || Session.getActiveUser().getEmail();
  const date = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'M/d');
  GmailApp.sendEmail(to, '[Gmail要約] ' + date + ' 判断待ち' + ask.length + '件・注目' + log.pick.length + '件',
    lines.join('\n'));

  // 判断待ちは答えが出るまで翌日の要約にも載せる
  const fresh = emptyLog_();
  fresh.ask = ask;
  saveLog_(fresh);
}

// ===== 補助 =====

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function threadLink_(id) {
  return 'https://mail.google.com/mail/u/0/#all/' + id;
}

function round2_(x) {
  return Math.round(x * 100) / 100;
}

function shortFrom_(from) {
  return from.replace(/<.*>/, '').replace(/"/g, '').trim() || from;
}

function emptyLog_() {
  return { pick: [], check: [], reply: [], ask: [], counts: { jobOther: 0, ad: 0, notice: 0, spam: 0, trash: 0, keep: 0 } };
}

// 要約用の記録は一覧ごとに別のプロパティへ保存する（1つあたり9KBの上限を超えないように）
const LOG_LISTS = ['pick', 'check', 'reply', 'ask'];

function loadLog_() {
  const props = PropertiesService.getScriptProperties();
  const log = emptyLog_();
  LOG_LISTS.forEach(k => {
    const raw = props.getProperty('log_' + k);
    if (raw) log[k] = JSON.parse(raw);
  });
  const counts = props.getProperty('log_counts');
  if (counts) Object.assign(log.counts, JSON.parse(counts));
  return log;
}

function saveLog_(log) {
  const props = PropertiesService.getScriptProperties();
  // 件名・差出人・理由は短くし、各一覧は直近15件まで
  const trim = list => list.slice(-15).map(m => ({
    id: m.id, s: (m.s || '').slice(0, 40), f: (m.f || '').slice(0, 25), r: (m.r || '').slice(0, 40),
  }));
  LOG_LISTS.forEach(k => props.setProperty('log_' + k, JSON.stringify(trim(log[k]))));
  props.setProperty('log_counts', JSON.stringify(log.counts));
}
