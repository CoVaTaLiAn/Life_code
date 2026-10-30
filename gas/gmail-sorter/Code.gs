/**
 * Gmail 自動振り分け + 毎朝の要約メール（Google Apps Script）
 *
 * AIを使わずルールだけで動くため、Claudeのトークンは消費しない。
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
  },

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

  // 既読だけにして受信箱に残す送信元（領収書・自動タスク通知など）
  noticeSenders: ['tm.openai.com', 'invoice@', 'mail.anthropic.com'],

  // 未読のまま残して要約で知らせる（セキュリティ系）
  checkKeywords: [
    'Security alert', 'セキュリティ', 'new device', 'ログイン', 'shared some Google Account data',
    'パスワード', '不正',
  ],
};

// ===== 初回だけ手動で実行する =====

function setup() {
  Object.values(CONFIG.labels).forEach(getOrCreateLabel_);
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sortInbox').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('sendSummary').timeBased().everyDays(1).atHour(CONFIG.summaryHour).create();
  sortInbox();
}

// ===== 1時間ごと：振り分け =====

function sortInbox() {
  const L = {};
  Object.entries(CONFIG.labels).forEach(([k, name]) => (L[k] = getOrCreateLabel_(name)));

  const threads = GmailApp.search('in:inbox is:unread has:nouserlabels', 0, CONFIG.maxThreads);
  const log = loadLog_();

  threads.forEach(thread => {
    const msg = thread.getMessages().slice(-1)[0];
    const from = msg.getFrom().toLowerCase();
    const subject = msg.getSubject() || '';
    const text = subject + ' ' + msg.getPlainBody().slice(0, 1500);
    const kind = classify_(from, subject, text);

    switch (kind) {
      case 'pick':
        thread.addLabel(L.pick);
        log.pick.push({ s: subject, f: shortFrom_(msg.getFrom()), id: thread.getId() });
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
      case 'check':
        thread.addLabel(L.check);
        log.check.push({ s: subject, f: shortFrom_(msg.getFrom()), id: thread.getId() });
        break;
      default:
        log.counts.other++; // 判定できないものは触らない
    }
  });

  saveLog_(log);
}

function classify_(from, subject, text) {
  // 送信元は小文字で比較、キーワードは大文字小文字を区別（"AI" が "mail" に当たらないように）
  const fromHas = list => list.some(k => from.includes(k.toLowerCase()));
  const has = (list, s) => list.some(k => s.includes(k));

  if (subject.startsWith('[Gmail要約]')) return 'none';
  if (fromHas(CONFIG.jobSenders)) {
    if (has(CONFIG.pickKeywords, text) && !has(CONFIG.dropKeywords, text)) return 'pick';
    return 'jobOther';
  }
  if (fromHas(CONFIG.noticeSenders)) return 'notice';
  if (has(CONFIG.checkKeywords, subject)) return 'check';
  if (fromHas(CONFIG.adSenders)) return 'ad';
  return 'none';
}

// ===== 毎朝：要約メール =====

function sendSummary() {
  const log = loadLog_();
  const link = id => 'https://mail.google.com/mail/u/0/#all/' + id;
  const c = log.counts;
  const lines = [];

  lines.push('【転職/注目】' + log.pick.length + '件');
  log.pick.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）\n  ' + link(m.id)));
  if (!log.pick.length) lines.push('- なし');

  lines.push('', '【要確認】' + log.check.length + '件');
  log.check.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）\n  ' + link(m.id)));
  if (!log.check.length) lines.push('- なし');

  lines.push('', '【自動処理】',
    '- 転職/その他：' + c.jobOther + '件（既読・アーカイブ）',
    '- 広告：' + c.ad + '件（既読・アーカイブ）',
    '- 通知：' + c.notice + '件（既読）',
    '- 未分類：' + c.other + '件（受信箱に残したまま）');

  const to = CONFIG.summaryTo || Session.getActiveUser().getEmail();
  const date = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'M/d');
  GmailApp.sendEmail(to, '[Gmail要約] ' + date + ' 注目' + log.pick.length + '件', lines.join('\n'));

  PropertiesService.getScriptProperties().deleteProperty('log');
}

// ===== 補助 =====

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function shortFrom_(from) {
  return from.replace(/<.*>/, '').replace(/"/g, '').trim() || from;
}

function loadLog_() {
  const raw = PropertiesService.getScriptProperties().getProperty('log');
  return raw ? JSON.parse(raw) : { pick: [], check: [], counts: { jobOther: 0, ad: 0, notice: 0, other: 0 } };
}

function saveLog_(log) {
  // プロパティの容量上限（9KB）を超えないよう、件名は60文字・各一覧は直近20件まで
  const trim = list => list.slice(-20).map(m => ({ ...m, s: m.s.slice(0, 60) }));
  log.pick = trim(log.pick);
  log.check = trim(log.check);
  PropertiesService.getScriptProperties().setProperty('log', JSON.stringify(log));
}
