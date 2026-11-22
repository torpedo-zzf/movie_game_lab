/* =========================================================
 * 《猫眼之后》互动播放器 · T-015
 * 纯静态 / 零依赖 / 零构建
 *
 * 数据：../story/03_storyboards/chapter_01.json
 * 资产：../assets/videos/<node_id>.mp4
 *       ../assets/frames/chapter_01/<node_id>_first.png（缺失兜底）
 *
 * 状态机：loading → playing → choosing → transitioning → ended
 * 非法跳转只告警并忽略，不改变当前状态。
 * ========================================================= */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ *
   * 常量与配置
   * ------------------------------------------------------------------ */

  var CHAPTER_URL = new URL('../story/03_storyboards/chapter_01.json', document.baseURI);
  var ROOT_URL = new URL('../', document.baseURI);
  var PARAMS = new URLSearchParams(window.location.search);

  var STATES = ['loading', 'playing', 'choosing', 'transitioning', 'ended'];

  // 明确列出合法迁移；其余一律忽略并打日志。
  var ALLOWED_TRANSITIONS = {
    loading: ['playing', 'transitioning', 'ended'],
    playing: ['choosing', 'transitioning', 'ended', 'loading'],
    choosing: ['transitioning', 'ended', 'loading'],
    transitioning: ['playing', 'ended', 'loading'],
    ended: ['loading', 'transitioning', 'playing']
  };

  var CHAPTER_TITLE = '猫眼之后';
  var DEFAULT_VIDEO_DURATION = 7;

  // 非选择节点的切镜策略（可用 ?advance=trigger 或调试面板切换）：
  //   ended   —— 播完再走 default_next_node（规格 3.3 / 3.4 的权威行为）
  //   trigger —— 到达 trigger_time_sec 即切镜（验收 6.1 的字面行为）
  var ADVANCE_MODES = ['ended', 'trigger'];
  var advanceMode = ADVANCE_MODES.indexOf(PARAMS.get('advance')) >= 0
    ? PARAMS.get('advance')
    : 'ended';

  // 调试：?missing=ch01_s02_peephole 或 ?missing=all 模拟视频 404。
  var forceMissingAll = PARAMS.get('missing') === 'all';
  var FORCE_MISSING = new Set(
    (PARAMS.get('missing') || '')
      .split(',')
      .map(function (s) { return s.trim(); })
      .filter(Boolean)
  );

  // s08 的 0–3s 是 AI 生成的手机聊天特写（屏幕文字乱码），
  // 播放时叠加真实 HTML 群聊气泡补足信息。
  var CHAT_OVERLAYS = {
    ch01_s08_groupchat: { until: 3.0 }
  };

  var ENDING_META = {
    ch01_s11_end_testify: { code: '结局 A', title: '交出录音' },
    ch01_s12_end_silence: { code: '结局 B', title: '删掉录音' }
  };

  var ITEM_LABELS = {
    item_brass_key: '黄铜钥匙',
    item_phone: '手机',
    item_recording: '录音',
    item_peephole_sticker: '同款猫眼贴纸',
    item_maintenance_sign: '维修中牌子'
  };

  var NODE_TYPE_LABELS = {
    video_play: '叙事',
    choice_branch: '选择',
    item_discovery: '道具',
    qte_event: 'QTE',
    ending: '结局'
  };

  /* ------------------------------------------------------------------ *
   * DOM
   * ------------------------------------------------------------------ */

  function $(id) { return document.getElementById(id); }

  var els = {
    app: $('app'),
    itemList: $('item-list'),
    debugBtn: $('debug-btn'),

    poster: $('poster'),
    videoLayer: $('video-layer'),
    fallback: $('fallback'),
    fallbackText: $('fallback-text'),
    fallbackSkip: $('fallback-skip'),
    chatOverlay: $('chat-overlay'),
    videoLoading: $('video-loading'),
    resumePrompt: $('resume-prompt'),
    resumeBtn: $('resume-btn'),

    subtitle: $('subtitle'),
    speaker: $('speaker'),
    dialogue: $('dialogue'),

    choiceLayer: $('choice-layer'),
    choiceContext: $('choice-context'),
    options: $('options'),
    countdown: $('countdown'),
    countdownNum: $('countdown-num'),
    ring: $('ring-fg'),
    choiceHint: $('choice-hint'),

    startScreen: $('start-screen'),
    startCover: $('start-cover'),
    startBtn: $('start-btn'),
    startStatus: $('start-status'),
    metaNodes: $('meta-nodes'),
    metaEndings: $('meta-endings'),
    metaDuration: $('meta-duration'),

    ending: $('ending'),
    endingCode: $('ending-code'),
    endingTitle: $('ending-title'),
    endingQuote: $('ending-quote'),
    endingMeta: $('ending-meta'),
    endingPathDetails: $('ending-path-details'),
    endingPath: $('ending-path'),
    pathCount: $('path-count'),
    replayBtn: $('replay-btn'),
    rewindBtn: $('rewind-btn'),

    errorScreen: $('error-screen'),
    errorMsg: $('error-msg'),
    errorDetail: $('error-detail'),
    retryBtn: $('retry-btn'),

    debugPanel: $('debug-panel'),
    debugClose: $('debug-close'),
    dbgState: $('dbg-state'),
    dbgNode: $('dbg-node'),
    dbgType: $('dbg-type'),
    dbgTime: $('dbg-time'),
    dbgTrigger: $('dbg-trigger'),
    dbgMode: $('dbg-mode'),
    dbgItems: $('dbg-items'),
    dbgPathlen: $('dbg-pathlen'),
    debugAdvance: $('debug-advance'),
    debugReset: $('debug-reset'),
    debugClearItems: $('debug-clear-items'),
    debugNodeList: $('debug-node-list'),
    debugPathList: $('debug-path-list'),

    toast: $('toast')
  };

  /* ------------------------------------------------------------------ *
   * 运行时状态
   * ------------------------------------------------------------------ */

  var app = {
    state: 'loading',
    started: false,
    chapter: null,
    nodes: new Map(),
    nodeOrder: [],
    firstChoiceId: null,

    currentNode: null,
    currentVideo: null,
    nodeStartedAt: 0,
    runToken: 0,

    path: [],
    items: new Set(),

    availability: new Map(),   // node_id -> true | false
    probes: new Map(),         // node_id -> Promise<boolean|null>
    preloads: new Map(),       // node_id -> detached <video>

    choice: null,
    choiceTimer: null,
    fallback: null,            // { startAt, duration } 用于视频缺失时的合成时间轴

    chatOn: false,
    endingShown: false,
    endingHideTimer: null,

    debugOpen: false,
    debugButtons: new Map(),
    debugFlags: new Map(),
    lastDebugPaint: 0,

    toastTimer: null,
    resumePending: false
  };

  /* ------------------------------------------------------------------ *
   * 基础工具
   * ------------------------------------------------------------------ */

  function log() {
    var args = Array.prototype.slice.call(arguments);
    args.unshift('[player]');
    console.log.apply(console, args);
  }

  function warn() {
    var args = Array.prototype.slice.call(arguments);
    args.unshift('[player]');
    console.warn.apply(console, args);
  }

  function assetUrl(path) {
    if (!path) return '';
    return new URL(String(path).replace(/^\.?\//, ''), ROOT_URL).href;
  }

  function toNumber(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function shortLabel(nodeId) {
    var m = /^ch\d+_(s\d+)/.exec(String(nodeId || ''));
    return m ? m[1].toUpperCase() : String(nodeId || '').slice(0, 4);
  }

  function nodeTypeLabel(type) {
    return NODE_TYPE_LABELS[type] || type || '—';
  }

  function itemLabel(itemId) {
    return ITEM_LABELS[itemId] || String(itemId || '').replace(/^item_/, '').replace(/_/g, ' ');
  }

  function videoDurationOf(node) {
    var d = node && node.video ? toNumber(node.video.duration_sec) : null;
    if (d && d > 0) return d;
    if (node && node.node_type === 'choice_branch') return 8;
    return DEFAULT_VIDEO_DURATION;
  }

  function isChoiceNode(node) {
    // schema 允许 item_discovery / qte_event 也带 options（例如拾取道具）；
    // 只要非结局节点配置了选项，就进入限时选择流程。
    return !!node &&
      node.node_type !== 'ending' &&
      Array.isArray(node.interaction && node.interaction.options) &&
      node.interaction.options.length > 0;
  }

  function setState(next, meta) {
    if (STATES.indexOf(next) < 0) {
      warn('未知状态，忽略：', next, meta || '');
      return false;
    }
    if (next === app.state) return true;
    var allowed = ALLOWED_TRANSITIONS[app.state] || [];
    if (allowed.indexOf(next) < 0) {
      warn('非法状态跳转，已忽略：' + app.state + ' → ' + next, meta || '');
      return false;
    }
    log('state', app.state, '→', next, meta || '');
    app.state = next;
    if (els.app) els.app.dataset.state = next;
    document.body.dataset.state = next;
    updateDebug();
    return true;
  }

  function showToast(message, tone) {
    if (!message) return;
    if (app.toastTimer) clearTimeout(app.toastTimer);
    els.toast.textContent = message;
    els.toast.classList.toggle('is-error', tone === 'error');
    els.toast.hidden = false;
    // 强制 reflow，保证连续 toast 也能重新播放过渡
    void els.toast.offsetWidth;
    els.toast.classList.add('is-on');
    app.toastTimer = setTimeout(function () {
      els.toast.classList.remove('is-on');
      app.toastTimer = null;
      setTimeout(function () {
        if (!els.toast.classList.contains('is-on')) els.toast.hidden = true;
      }, 220);
    }, 2400);
  }

  /* ------------------------------------------------------------------ *
   * 数据载入
   * ------------------------------------------------------------------ */

  function boot() {
    bindEvents();
    renderItems();
    updateDebug();
    requestAnimationFrame(tick);
    loadChapter();
  }

  async function loadChapter() {
    try {
      if (window.location.protocol === 'file:') {
        throw new Error('当前页面以 file:// 打开，浏览器禁止 fetch 本地章节 JSON。');
      }
      var res = await fetch(CHAPTER_URL.href, { cache: 'no-store' });
      if (!res.ok) {
        throw new Error('章节 JSON 读取失败：HTTP ' + res.status + ' ' + (res.statusText || ''));
      }
      var data = await res.json();
      validateChapter(data);
      applyChapter(data);
    } catch (err) {
      showFatal(err);
    }
  }

  function validateChapter(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('章节 JSON 顶层不是对象。');
    }
    if (!Array.isArray(data.nodes) || data.nodes.length === 0) {
      throw new Error('章节 JSON 的 nodes 为空。');
    }
    if (!data.start_node) {
      throw new Error('章节 JSON 缺少 start_node。');
    }
    var ids = new Set();
    data.nodes.forEach(function (node) {
      if (!node || typeof node !== 'object') throw new Error('nodes 中存在非对象节点。');
      if (!node.node_id) throw new Error('存在缺少 node_id 的节点。');
      if (ids.has(node.node_id)) throw new Error('node_id 重复：' + node.node_id);
      ids.add(node.node_id);
      if (!node.video || typeof node.video !== 'object') {
        throw new Error(node.node_id + ' 缺少 video 对象。');
      }
    });
    if (!ids.has(data.start_node)) {
      throw new Error('start_node 不在节点表中：' + data.start_node);
    }
    // 死链只告警，不阻断播放；静态自检会给出失败退出码。
    data.nodes.forEach(function (node) {
      var nexts = [];
      var it = node.interaction || {};
      if (it.default_next_node) nexts.push(it.default_next_node);
      (it.options || []).forEach(function (opt) {
        if (opt && opt.next_node) nexts.push(opt.next_node);
      });
      nexts.forEach(function (nextId) {
        if (!ids.has(nextId)) {
          warn('剧情图死链：' + node.node_id + ' → ' + nextId);
        }
      });
    });
  }

  function applyChapter(data) {
    app.chapter = data;
    app.nodes = new Map();
    app.nodeOrder = [];
    data.nodes.forEach(function (node) {
      app.nodes.set(node.node_id, node);
      app.nodeOrder.push(node.node_id);
    });

    var firstChoice = data.nodes.find(function (node) {
      return node.node_type === 'choice_branch' &&
        node.interaction &&
        Array.isArray(node.interaction.options) &&
        node.interaction.options.length > 0;
    });
    app.firstChoiceId = firstChoice ? firstChoice.node_id : null;

    var startNode = app.nodes.get(data.start_node);
    var endings = data.nodes.filter(function (n) { return n.node_type === 'ending'; }).length;
    var total = data.nodes.reduce(function (sum, n) {
      return sum + (toNumber(n.video && n.video.duration_sec) || 0);
    }, 0);

    els.metaNodes.textContent = data.nodes.length + ' 个节点';
    els.metaEndings.textContent = endings + ' 个结局';
    els.metaDuration.textContent = '约 ' + Math.round(total) + ' 秒';
    document.title = (data.title || CHAPTER_TITLE) + ' · 互动播放器';

    // 开始屏封面 = 起始节点首帧
    if (startNode && startNode.video && startNode.video.first_frame_path) {
      els.startCover.src = assetUrl(startNode.video.first_frame_path);
      els.startCover.onerror = function () { els.startCover.hidden = true; };
    } else {
      els.startCover.hidden = true;
    }

    els.startBtn.disabled = false;
    els.startBtn.textContent = '开始播放';
    els.startStatus.textContent = '已载入 ' + data.nodes.length + ' 个节点 · 正在预检视频…';

    renderDebugNodes();
    updateDebug();
    probeAllVideos();
  }

  function showFatal(err) {
    var message = err && err.message ? err.message : String(err);
    var isFile = window.location.protocol === 'file:';
    els.errorMsg.textContent = isFile
      ? '浏览器以 file:// 直接打开页面，无法读取章节 JSON。'
      : '章节数据读取失败。';
    var detail = message;
    if (isFile) {
      detail += '\n请从仓库根目录启动静态服务后访问 http://127.0.0.1:8123/player/';
    }
    if (err && err.stack) detail += '\n\n' + err.stack;
    els.errorDetail.textContent = detail;
    els.errorScreen.hidden = false;
    els.startBtn.disabled = true;
    els.startStatus.textContent = '载入失败：' + message;
    warn('章节载入失败：', err);
  }

  /* ------------------------------------------------------------------ *
   * 视频可用性预检（HEAD）+ 预加载
   * ------------------------------------------------------------------ */

  function probeVideo(node) {
    if (!node) return Promise.resolve(false);
    var id = node.node_id;
    if (forceMissingAll || FORCE_MISSING.has(id)) {
      app.availability.set(id, false);
      return Promise.resolve(false);
    }
    if (app.availability.has(id)) {
      return Promise.resolve(app.availability.get(id));
    }
    if (app.probes.has(id)) return app.probes.get(id);

    var path = node.video && node.video.video_path;
    if (!path) {
      app.availability.set(id, false);
      return Promise.resolve(false);
    }

    var url = assetUrl(path);
    var promise = (async function () {
      var controller = null;
      var timer = null;
      try {
        if (typeof AbortController === 'function') controller = new AbortController();
        if (controller) {
          timer = setTimeout(function () { controller.abort(); }, 5000);
        }
        var res = await fetch(url, {
          method: 'HEAD',
          cache: 'no-store',
          signal: controller ? controller.signal : undefined
        });
        if (res.ok) {
          app.availability.set(id, true);
          return true;
        }
        if (res.status === 405 || res.status === 501) {
          return null; // 服务器不支持 HEAD，交给 <video> error 事件判定
        }
        app.availability.set(id, false);
        return false;
      } catch (e) {
        // 网络/CORS/超时：状态未知，交给 <video> 自己报错。
        return null;
      } finally {
        if (timer) clearTimeout(timer);
      }
    })();

    app.probes.set(id, promise);
    promise.then(function () {
      updateDebugNodeFlags();
      updateStartStatus();
    });
    return promise;
  }

  function probeAllVideos() {
    var nodes = app.nodeOrder.map(function (id) { return app.nodes.get(id); }).filter(Boolean);
    Promise.all(nodes.map(probeVideo)).then(function () {
      updateDebugNodeFlags();
      updateStartStatus();
    });
  }

  function updateStartStatus() {
    if (!app.chapter) return;
    var nodes = app.nodeOrder.map(function (id) { return app.nodes.get(id); }).filter(Boolean);
    var missing = 0;
    var known = 0;
    nodes.forEach(function (node) {
      var a = app.availability.get(node.node_id);
      if (a === false) missing += 1;
      if (a === true || a === false) known += 1;
    });
    if (forceMissingAll || FORCE_MISSING.size) {
      els.startStatus.textContent = '调试模式：强制 ' + missing + ' 个视频缺失，将以首帧占位试玩';
    } else if (missing > 0) {
      els.startStatus.textContent = missing + ' 个视频缺失 · 将以首帧 + 「视频生成中」继续';
    } else if (known < nodes.length) {
      els.startStatus.textContent = '视频预检 ' + known + '/' + nodes.length + ' · 其余按需载入';
    } else {
      els.startStatus.textContent = '视频预检 ' + nodes.length + '/' + nodes.length + ' 就绪';
    }
  }

  function schedulePreload(node) {
    var ids = [];
    var it = node.interaction || {};
    if (isChoiceNode(node)) {
      it.options.forEach(function (opt) {
        if (opt && opt.next_node) ids.push(opt.next_node);
      });
      if (it.default_next_node) ids.push(it.default_next_node);
    } else if (it.default_next_node) {
      ids.push(it.default_next_node);
    }
    if (node.node_type === 'ending') return;

    ids = Array.from(new Set(ids)).filter(function (id) {
      var n = app.nodes.get(id);
      return !!n && !!(n.video && n.video.video_path) && app.availability.get(id) !== false;
    });

    // 不再需要的预加载立刻释放
    Array.from(app.preloads.keys()).forEach(function (id) {
      if (ids.indexOf(id) < 0) destroyPreload(id);
    });

    ids.forEach(function (id) {
      if (app.preloads.has(id)) return;
      var n = app.nodes.get(id);
      var v = document.createElement('video');
      v.preload = 'auto';
      v.muted = true;
      v.playsInline = true;
      v.src = assetUrl(n.video.video_path);
      v.load();
      app.preloads.set(id, v);
    });
  }

  function destroyPreload(id) {
    var v = app.preloads.get(id);
    if (!v) return;
    try { v.pause(); } catch (e) { /* ignore */ }
    v.removeAttribute('src');
    try { v.load(); } catch (e) { /* ignore */ }
    app.preloads.delete(id);
  }

  function destroyAllPreloads() {
    Array.from(app.preloads.keys()).forEach(destroyPreload);
  }

  /* ------------------------------------------------------------------ *
   * 媒体元素
   * ------------------------------------------------------------------ */

  function createVideoEl(node) {
    var v = document.createElement('video');
    v.className = 'video-el';
    v.preload = 'auto';
    v.playsInline = true;
    v.setAttribute('playsinline', '');
    v.setAttribute('webkit-playsinline', '');
    v.dataset.nodeId = node.node_id;
    v.src = assetUrl(node.video.video_path);
    v.load();
    return v;
  }

  function waitForVideo(video, timeoutMs) {
    return new Promise(function (resolve) {
      if (video.readyState >= 2) {
        resolve('ready');
        return;
      }
      var settled = false;
      var timer = null;

      function cleanup() {
        if (timer) clearTimeout(timer);
        video.removeEventListener('loadeddata', onReady);
        video.removeEventListener('canplay', onReady);
        video.removeEventListener('error', onError);
      }

      function finish(result) {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(result);
      }

      function onReady() { finish('ready'); }
      function onError() { finish('error'); }

      timer = setTimeout(function () { finish('timeout'); }, timeoutMs);
      video.addEventListener('loadeddata', onReady);
      video.addEventListener('canplay', onReady);
      video.addEventListener('error', onError);
    });
  }

  function destroyVideo(video) {
    if (!video) return;
    try { video.pause(); } catch (e) { /* ignore */ }
    video.removeAttribute('src');
    try { video.load(); } catch (e) { /* ignore */ }
    if (video.parentNode) video.parentNode.removeChild(video);
  }

  function showPoster(node) {
    var path = node.video && node.video.first_frame_path;
    if (!path) {
      els.poster.classList.add('is-empty');
      els.poster.removeAttribute('src');
      return;
    }
    els.poster.classList.remove('is-empty');
    els.poster.classList.remove('is-broken');
    els.poster.src = assetUrl(path);
  }

  function setVideoLoading(show) {
    els.videoLoading.hidden = !show;
  }

  function hideFallbackUI() {
    els.fallback.hidden = true;
  }

  function showFallbackUI(node) {
    els.fallback.hidden = false;
    els.fallbackText.textContent = shortLabel(node.node_id) + ' · 首帧占位，流程可继续';
    setVideoLoading(false);
  }

  function startFallback(node, fromTime) {
    var duration = videoDurationOf(node);
    var t = Math.max(0, toNumber(fromTime) || 0);
    app.fallback = {
      startAt: (typeof performance !== 'undefined' ? performance.now() : Date.now()) - t * 1000,
      duration: duration
    };
  }

  function getPlayhead() {
    if (app.fallback) {
      var now = typeof performance !== 'undefined' ? performance.now() : Date.now();
      return Math.max(0, (now - app.fallback.startAt) / 1000);
    }
    var v = app.currentVideo;
    if (!v) return 0;
    if (Number.isFinite(v.currentTime)) return v.currentTime;
    return 0;
  }

  function fadeOutOld(oldVideo, token) {
    if (!oldVideo) return;
    oldVideo.classList.remove('is-live');
    oldVideo.style.opacity = '0';
    setTimeout(function () {
      if (oldVideo !== app.currentVideo) destroyVideo(oldVideo);
    }, 180);
  }

  function activateVideo(video, oldVideo) {
    video.classList.add('is-live');
    video.style.opacity = '1';
    if (oldVideo && oldVideo !== video) {
      oldVideo.classList.remove('is-live');
      oldVideo.style.opacity = '0';
      setTimeout(function () {
        if (oldVideo !== app.currentVideo) destroyVideo(oldVideo);
      }, 180);
    }
  }

  function showResumePrompt() {
    app.resumePending = true;
    els.resumePrompt.hidden = false;
  }

  function hideResumePrompt() {
    app.resumePending = false;
    els.resumePrompt.hidden = true;
  }

  /* ------------------------------------------------------------------ *
   * 节点进入 / 切镜
   * ------------------------------------------------------------------ */

  async function enterNode(nodeId, opts) {
    opts = opts || {};
    var node = app.nodes.get(nodeId);
    if (!node) {
      warn('节点不存在，无法进入：', nodeId);
      showToast('节点不存在：' + nodeId, 'error');
      return;
    }

    var token = ++app.runToken;
    clearChoice();
    hideEnding(true);
    setChat(false);
    hideResumePrompt();
    hideFallbackUI();
    setVideoLoading(false);

    app.currentNode = node;
    app.nodeStartedAt = now();
    app.fallback = null;
    app.endingShown = false;
    app.lastPlayhead = 0;

    if (opts.resetPath) app.path = [];
    recordPath(node, opts);
    renderSubtitle(node);
    showPoster(node);
    renderItems();
    renderDebugPath();
    setState('transitioning', 'enter:' + nodeId);
    updateDebug();

    var oldVideo = app.currentVideo;
    if (oldVideo) {
      try { oldVideo.pause(); } catch (e) { /* ignore */ }
    }
    app.currentVideo = null;

    // 节点级道具（schema 未定义，但兼容 item_discovery 的可选扩展）
    if (Array.isArray(node.grant_items) && node.grant_items.length) {
      grantItems(node.grant_items);
    }

    var forced = forceMissingAll || FORCE_MISSING.has(nodeId);
    var available = forced ? false : app.availability.get(nodeId);
    if (available === undefined) {
      available = await probeVideo(node);
      if (token !== app.runToken) return;
    }

    if (forced || available === false) {
      enterFallback(node, oldVideo, token, 0);
      return;
    }

    var video = null;
    if (node.video && node.video.video_path) {
      video = createVideoEl(node);
      els.videoLayer.appendChild(video);
      video.style.opacity = '0';
      setVideoLoading(true);
      var ready = await waitForVideo(video, 6000);
      setVideoLoading(false);
      if (token !== app.runToken) {
        destroyVideo(video);
        return;
      }
      if (ready === 'ready') {
        app.availability.set(node.node_id, true);
      } else {
        warn('视频未能就绪（' + ready + '）：', node.node_id, node.video.video_path);
        app.availability.set(node.node_id, false);
        destroyVideo(video);
        video = null;
      }
    }

    if (!video) {
      enterFallback(node, oldVideo, token, 0);
      return;
    }

    app.currentVideo = video;
    video.addEventListener('ended', function () { handleVideoEnded(video); });
    video.addEventListener('error', function () { handleVideoRuntimeError(video); });

    var playResult = video.play();
    activateVideo(video, oldVideo);
    setState('playing', 'video:' + node.node_id);
    schedulePreload(node);

    if (playResult && typeof playResult.catch === 'function') {
      playResult.catch(function (err) {
        if (token !== app.runToken) return;
        if (err && err.name === 'NotAllowedError') {
          showResumePrompt();
        } else {
          warn('play() 失败：', err);
          showResumePrompt();
        }
      });
    }

    app.nodeStartedAt = now();
    updateDebug();
  }

  function enterFallback(node, oldVideo, token, fromTime) {
    app.currentVideo = null;
    startFallback(node, fromTime || 0);
    showFallbackUI(node);
    fadeOutOld(oldVideo, token);
    setState('playing', 'fallback:' + node.node_id);
    schedulePreload(node);
    updateDebug();
    if (token !== app.runToken) return;
  }

  function advanceNode(nextId, opts) {
    opts = opts || {};
    if (!nextId) {
      warn('节点没有 default_next_node，无法推进：', app.currentNode && app.currentNode.node_id);
      return;
    }
    if (!app.nodes.has(nextId)) {
      warn('next_node 不存在：', nextId);
      showToast('剧情图死链：' + nextId, 'error');
      return;
    }
    enterNode(nextId, opts);
  }

  function handleVideoEnded(video) {
    if (video !== app.currentVideo) return;
    var node = app.currentNode;
    if (!node) return;

    if (node.node_type === 'ending') {
      showEnding(node);
      return;
    }
    if (app.state === 'choosing') {
      resolveDefault('ended');
      return;
    }
    if (app.state !== 'playing') return;

    var next = node.interaction && node.interaction.default_next_node;
    if (next) {
      advanceNode(next, { via: 'ended' });
    } else {
      warn('非结局节点缺少 default_next_node：', node.node_id);
      showToast('当前节点没有出口，停在片尾', 'error');
      setState('ended', 'no-next');
      app.endingShown = true;
    }
  }

  function handleVideoRuntimeError(video) {
    if (video !== app.currentVideo) return;
    var node = app.currentNode;
    if (!node) return;
    var t = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    warn('播放中视频失效，切换到首帧占位：', node.node_id);
    app.availability.set(node.node_id, false);
    app.currentVideo = null;
    destroyVideo(video);
    startFallback(node, t);
    showFallbackUI(node);
    if (app.state === 'choosing') {
      // 保持选择状态与倒计时，时间轴由 fallback 接管
    } else if (app.state === 'transitioning') {
      setState('playing', 'runtime-error');
    }
    updateDebug();
    updateDebugNodeFlags();
  }

  /* ------------------------------------------------------------------ *
   * 字幕 / 路径 / 道具
   * ------------------------------------------------------------------ */

  function renderSubtitle(node) {
    els.speaker.textContent = node.speaker || '';
    els.speaker.hidden = !node.speaker;
    els.dialogue.textContent = node.dialogue || '';
    els.dialogue.hidden = !node.dialogue;
    els.subtitle.classList.remove('is-in');
    // 强制 reflow 以重播淡入
    void els.subtitle.offsetWidth;
    requestAnimationFrame(function () {
      els.subtitle.classList.add('is-in');
    });
  }

  function recordPath(node, opts) {
    app.path.push({
      node_id: node.node_id,
      node_type: node.node_type,
      speaker: node.speaker || '',
      dialogue: node.dialogue || '',
      option_id: null,
      option_label: null,
      via: (opts && opts.via) || 'default',
      at: Date.now()
    });
    renderDebugPath();
  }

  function markPathEntry(patch) {
    var entry = app.path[app.path.length - 1];
    if (!entry) return;
    Object.keys(patch).forEach(function (k) { entry[k] = patch[k]; });
    renderDebugPath();
  }

  function renderItems() {
    els.itemList.replaceChildren();
    if (app.items.size === 0) {
      var empty = document.createElement('span');
      empty.className = 'item-empty';
      empty.textContent = '空';
      els.itemList.appendChild(empty);
      return;
    }
    app.items.forEach(function (id) {
      var chip = document.createElement('span');
      chip.className = 'item-chip';
      chip.textContent = itemLabel(id);
      chip.title = id;
      els.itemList.appendChild(chip);
    });
  }

  function grantItems(ids) {
    if (!Array.isArray(ids)) return;
    var granted = [];
    ids.forEach(function (id) {
      if (!id || app.items.has(id)) return;
      app.items.add(id);
      granted.push(itemLabel(id));
    });
    if (!granted.length) return;
    renderItems();
    updateDebug();
    showToast('获得道具 · ' + granted.join('、'));
  }

  function hasRequiredItems(option) {
    var required = Array.isArray(option && option.required_items) ? option.required_items : [];
    return required.every(function (id) { return app.items.has(id); });
  }

  function missingItems(option) {
    var required = Array.isArray(option && option.required_items) ? option.required_items : [];
    return required.filter(function (id) { return !app.items.has(id); });
  }

  /* ------------------------------------------------------------------ *
   * 选择
   * ------------------------------------------------------------------ */

  function openChoice(node) {
    if (app.state !== 'playing' || app.choice) return;
    var options = (node.interaction && Array.isArray(node.interaction.options))
      ? node.interaction.options
      : [];
    if (!options.length) return;

    var timeoutSec = toNumber(node.interaction && node.interaction.timeout_sec);
    var hasTimeout = timeoutSec !== null && timeoutSec > 0;
    var deadline = hasTimeout ? now() + timeoutSec * 1000 : null;

    app.choice = {
      options: options,
      deadline: deadline,
      timeoutSec: hasTimeout ? timeoutSec : 0,
      resolved: false,
      openedAt: now()
    };

    renderOptions(node);

    // 选择时全屏 scrim 会压暗底部字幕，把当前台词同步一份进卡片，
    // 确保玩家在做决定时仍能读到上下文。
    els.choiceContext.replaceChildren();
    if (node.dialogue) {
      if (node.speaker) {
        var who = document.createElement('span');
        who.className = 'choice-context-speaker';
        who.textContent = node.speaker;
        els.choiceContext.appendChild(who);
      }
      els.choiceContext.appendChild(document.createTextNode(node.dialogue));
      els.choiceContext.hidden = false;
    } else {
      els.choiceContext.hidden = true;
    }

    els.choiceLayer.hidden = false;
    void els.choiceLayer.offsetWidth;
    els.choiceLayer.classList.add('is-on');
    document.body.classList.add('is-choosing');
    setState('choosing', 'choice:' + node.node_id);
    updateCountdownUI();

    if (deadline) {
      app.choiceTimer = setTimeout(function () {
        resolveDefault('timeout');
      }, Math.max(0, deadline - now()));
    }
    updateDebug();
  }

  function renderOptions(node) {
    els.options.replaceChildren();
    var options = node.interaction.options;
    options.forEach(function (opt, index) {
      var missing = missingItems(opt);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'option-btn';
      btn.dataset.optionId = opt.option_id || ('opt_' + index);
      btn.disabled = missing.length > 0;

      var key = document.createElement('span');
      key.className = 'option-key';
      key.textContent = String(index + 1);

      var label = document.createElement('span');
      label.className = 'option-label';
      label.textContent = opt.label || opt.option_id || ('选项 ' + (index + 1));

      btn.appendChild(key);
      btn.appendChild(label);

      if (missing.length) {
        var miss = document.createElement('span');
        miss.className = 'option-missing';
        miss.textContent = '缺少：' + missing.map(itemLabel).join('、');
        btn.appendChild(miss);
        btn.title = '缺少道具：' + missing.map(itemLabel).join('、');
      }

      btn.addEventListener('click', function () {
        selectOption(opt, 'pointer');
      });
      els.options.appendChild(btn);
    });

    var count = options.length;
    els.choiceHint.innerHTML = '';
    var keyHint = document.createElement('span');
    var keys = [];
    for (var i = 1; i <= Math.min(count, 9); i += 1) keys.push(i);
    keyHint.appendChild(document.createTextNode('按 '));
    keys.forEach(function (n, idx) {
      var kbd = document.createElement('kbd');
      kbd.textContent = String(n);
      keyHint.appendChild(kbd);
      if (idx < keys.length - 1) keyHint.appendChild(document.createTextNode(' / '));
    });
    keyHint.appendChild(document.createTextNode(' 选择'));
    var timeoutHint = document.createElement('span');
    timeoutHint.textContent = (toNumber(node.interaction.timeout_sec) || 0) > 0
      ? '超时将自动推进'
      : '做出你的选择';
    els.choiceHint.appendChild(keyHint);
    els.choiceHint.appendChild(timeoutHint);
    els.choiceHint.hidden = false;
  }

  function selectOption(option, source) {
    if (app.state !== 'choosing' || !app.choice || app.choice.resolved) return;
    var missing = missingItems(option);
    if (missing.length) {
      showToast('缺少道具：' + missing.map(itemLabel).join('、'), 'error');
      return;
    }

    app.choice.resolved = true;
    if (app.choiceTimer) {
      clearTimeout(app.choiceTimer);
      app.choiceTimer = null;
    }

    var node = app.currentNode;
    var token = app.runToken;
    markPathEntry({
      option_id: option.option_id || null,
      option_label: option.label || option.option_id || '已选择',
      via: source || 'choice'
    });

    // 120ms 选中反馈后再切镜
    Array.prototype.forEach.call(els.options.children, function (btn) {
      var chosen = btn.dataset.optionId === option.option_id;
      btn.disabled = true;
      btn.classList.toggle('is-chosen', chosen);
    });

    setState('transitioning', 'option:' + option.option_id);
    updateDebug();

    setTimeout(function () {
      if (token !== app.runToken) return;
      if (app.currentNode !== node) return;
      grantItems(option.grant_items);
      advanceNode(option.next_node, { via: 'choice' });
    }, 120);
  }

  function resolveDefault(reason) {
    if (!app.choice || app.choice.resolved) return;
    var choice = app.choice;
    choice.resolved = true;
    if (app.choiceTimer) {
      clearTimeout(app.choiceTimer);
      app.choiceTimer = null;
    }

    var node = app.currentNode;
    if (!node) return;
    var token = app.runToken;
    var next = node.interaction && node.interaction.default_next_node;
    var defaultOpt = (node.interaction.options || []).find(function (opt) {
      return opt.next_node === next;
    });

    markPathEntry({
      option_id: defaultOpt ? (defaultOpt.option_id || null) : null,
      option_label: defaultOpt
        ? defaultOpt.label + '（自动）'
        : '默认推进',
      via: reason === 'ended' ? 'ended-default' : reason || 'default'
    });

    Array.prototype.forEach.call(els.options.children, function (btn) {
      btn.disabled = true;
      if (defaultOpt && btn.dataset.optionId === defaultOpt.option_id) {
        btn.classList.add('is-chosen');
      }
    });

    if (reason === 'timeout') {
      showToast('未做选择 · 自动推进', 'muted');
    }

    setState('transitioning', 'default:' + reason);
    updateDebug();

    setTimeout(function () {
      if (token !== app.runToken) return;
      if (app.currentNode !== node) return;
      advanceNode(next, { via: reason === 'ended' ? 'ended' : 'default' });
    }, 160);
  }

  function clearChoice() {
    if (app.choiceTimer) {
      clearTimeout(app.choiceTimer);
      app.choiceTimer = null;
    }
    app.choice = null;
    if (els.choiceLayer) {
      els.choiceLayer.classList.remove('is-on');
      els.choiceLayer.hidden = true;
    }
    if (els.options) els.options.replaceChildren();
    if (els.choiceContext) {
      els.choiceContext.replaceChildren();
      els.choiceContext.hidden = true;
    }
    document.body.classList.remove('is-choosing');
  }

  function updateCountdownUI() {
    var choice = app.choice;
    if (!choice) return;
    if (!choice.deadline || !choice.timeoutSec) {
      els.countdown.hidden = true;
      return;
    }
    els.countdown.hidden = false;
    var remain = Math.max(0, (choice.deadline - now()) / 1000);
    els.countdownNum.textContent = remain > 0.05 ? remain.toFixed(1) : '0';
    var circumference = 2 * Math.PI * 18;
    var fraction = Math.min(1, remain / choice.timeoutSec);
    els.ring.style.strokeDashoffset = String(circumference * (1 - fraction));
    els.countdown.classList.toggle('is-urgent', remain <= 1.0 && remain > 0);
  }

  /* ------------------------------------------------------------------ *
   * 结局
   * ------------------------------------------------------------------ */

  function showEnding(node) {
    if (app.endingShown) return;
    app.endingShown = true;
    clearChoice();
    setChat(false);
    hideFallbackUI();
    setVideoLoading(false);

    if (app.currentVideo) {
      try { app.currentVideo.pause(); } catch (e) { /* ignore */ }
    }

    var meta = ENDING_META[node.node_id] || {
      code: '结局',
      title: node.speaker ? node.speaker + '的结局' : '故事结束'
    };

    els.endingCode.textContent = meta.code;
    els.endingTitle.textContent = meta.title;
    els.endingQuote.textContent = node.dialogue
      ? (node.speaker ? node.speaker + '：「' + node.dialogue + '」' : node.dialogue)
      : '';
    els.endingQuote.hidden = !node.dialogue;

    renderEndingMeta(node);
    renderEndingPath(node);

    if (els.endingHideTimer) {
      clearTimeout(els.endingHideTimer);
      els.endingHideTimer = null;
    }
    els.ending.hidden = false;
    void els.ending.offsetWidth;
    els.ending.classList.add('is-on');

    setState('ended', 'ending:' + node.node_id);
    updateDebug();

    setTimeout(function () {
      if (els.ending.hidden) return;
      try { els.replayBtn.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
    }, 360);
  }

  function renderEndingMeta(node) {
    els.endingMeta.replaceChildren();
    var choices = app.path.filter(function (e) {
      return e.option_label && e.node_type !== 'ending';
    });
    var timeouts = app.path.filter(function (e) {
      return e.via === 'timeout';
    });

    var chips = [];
    chips.push(app.chapter && app.chapter.title ? app.chapter.title : CHAPTER_TITLE);
    chips.push('节点 ' + app.path.length + ' 个');
    if (choices.length) chips.push('选择 ' + choices.length + ' 次');
    if (timeouts.length) chips.push('超时 ' + timeouts.length + ' 次');
    if (app.items.size) chips.push('道具 ' + app.items.size + ' 件');

    chips.forEach(function (text, index) {
      var chip = document.createElement('span');
      chip.className = 'ending-chip' + (index === 0 ? ' is-accent' : '');
      chip.textContent = text;
      els.endingMeta.appendChild(chip);
    });

    // 结局节点本身不计入选择摘要
    var summary = document.createElement('span');
    summary.className = 'ending-chip';
    summary.textContent = '达成 ' + (ENDING_META[node.node_id] ? ENDING_META[node.node_id].code : '结局');
    els.endingMeta.appendChild(summary);
  }

  function renderEndingPath() {
    els.endingPath.replaceChildren();
    app.path.forEach(function (entry) {
      var li = document.createElement('li');
      if (entry.option_label) li.classList.add('is-choice');
      if (entry.via === 'timeout' || entry.via === 'ended-default') li.classList.add('is-timeout');

      var nodeSpan = document.createElement('span');
      nodeSpan.className = 'path-node';
      nodeSpan.textContent = shortLabel(entry.node_id);

      var text = document.createElement('span');
      text.textContent = (entry.speaker ? entry.speaker + ' · ' : '') +
        (entry.dialogue || nodeTypeLabel(entry.node_type));

      li.appendChild(nodeSpan);
      li.appendChild(text);

      if (entry.option_label) {
        var choice = document.createElement('span');
        choice.className = 'path-choice';
        choice.textContent = ' → ' + entry.option_label;
        li.appendChild(choice);
      }

      if (entry.via === 'timeout') {
        var note = document.createElement('span');
        note.className = 'path-note';
        note.textContent = '（超时）';
        li.appendChild(note);
      }

      els.endingPath.appendChild(li);
    });
    els.pathCount.textContent = '· ' + app.path.length + ' 幕';
  }

  function hideEnding(immediate) {
    if (!els.ending) return;
    if (els.endingHideTimer) {
      clearTimeout(els.endingHideTimer);
      els.endingHideTimer = null;
    }
    els.ending.classList.remove('is-on');
    if (immediate) {
      els.ending.hidden = true;
    } else {
      els.endingHideTimer = setTimeout(function () {
        els.ending.hidden = true;
        els.endingHideTimer = null;
      }, 260);
    }
    app.endingShown = false;
  }

  /* ------------------------------------------------------------------ *
   * 重玩 / 重置
   * ------------------------------------------------------------------ */

  function startRun() {
    if (!app.chapter || app.started) return;
    app.started = true;
    els.startBtn.disabled = true;
    els.startBtn.textContent = '准备播放…';
    els.startScreen.classList.add('is-leaving');
    setTimeout(function () { els.startScreen.hidden = true; }, 230);
    resetRun(app.chapter.start_node);
  }

  function resetRun(startNodeId, pathPrefix) {
    app.runToken += 1;
    clearChoice();
    hideEnding(true);
    setChat(false);
    hideResumePrompt();
    hideFallbackUI();
    setVideoLoading(false);

    if (app.currentVideo) {
      destroyVideo(app.currentVideo);
      app.currentVideo = null;
    }
    destroyAllPreloads();
    app.fallback = null;
    app.endingShown = false;
    app.lastPlayhead = 0;
    app.items = new Set();
    renderItems();

    app.path = Array.isArray(pathPrefix) ? pathPrefix.map(function (e) {
      return Object.assign({}, e);
    }) : [];

    if (!els.startScreen.hidden) {
      // startRun() 里用 230ms 淡出；这里补一个兜底隐藏，避免调试重置后卡在遮罩层。
      els.startScreen.classList.add('is-leaving');
      setTimeout(function () { els.startScreen.hidden = true; }, 230);
    }

    setState('loading', 'reset');    enterNode(startNodeId, { via: 'restart' });
  }

  function restartFromFirstChoice() {
    if (!app.chapter) return;
    var firstChoice = app.firstChoiceId;
    if (!firstChoice) {
      resetRun(app.chapter.start_node);
      return;
    }

    // 沿默认链回填 s01…s03，让结局路径不丢前情
    var prefix = [];
    var cursor = app.chapter.start_node;
    var guard = 0;
    while (cursor && cursor !== firstChoice && guard < 50) {
      var node = app.nodes.get(cursor);
      if (!node) break;
      prefix.push({
        node_id: node.node_id,
        node_type: node.node_type,
        speaker: node.speaker || '',
        dialogue: node.dialogue || '',
        option_id: null,
        option_label: null,
        via: 'default',
        at: Date.now()
      });
      cursor = node.interaction && node.interaction.default_next_node;
      guard += 1;
    }
    resetRun(firstChoice, prefix);
    showToast('回到第一个选择 · ' + shortLabel(firstChoice));
  }

  /* ------------------------------------------------------------------ *
   * 主循环
   * ------------------------------------------------------------------ */

  function tick(nowTs) {
    var node = app.currentNode;
    if (node) {
      var t = getPlayhead();
      app.lastPlayhead = t;

      updateChat(node, t);

      if (app.state === 'playing') {
        if (isChoiceNode(node)) {
          var trigger = toNumber(node.interaction.trigger_time_sec);
          if (trigger !== null && trigger >= 0 && t >= trigger) {
            openChoice(node);
          }
        } else if (node.node_type !== 'ending' && advanceMode === 'trigger') {
          var cut = toNumber(node.interaction && node.interaction.trigger_time_sec);
          if (cut !== null && cut > 0 && t >= cut) {
            advanceNode(node.interaction && node.interaction.default_next_node, { via: 'trigger' });
          }
        }
      }

      if (app.state === 'choosing') {
        updateCountdownUI();
      }

      // 视频缺失时的合成时间轴：片尾推进 / 结局卡
      if (app.fallback && (app.state === 'playing' || app.state === 'choosing')) {
        if (node.node_type === 'ending') {
          if (t >= app.fallback.duration) showEnding(node);
        } else if (t >= app.fallback.duration) {
          if (app.state === 'choosing') {
            // 正常视频由 ended 事件兜底；合成时间轴需要显式收口。
            resolveDefault('ended');
          } else if (isChoiceNode(node)) {
            // trigger 被跳过或缺失时，片尾仍要把选择摆出来，再走默认。
            openChoice(node);
          } else if (advanceMode === 'ended') {
            advanceNode(node.interaction && node.interaction.default_next_node, { via: 'ended' });
          }
        }
      }

      if (app.debugOpen && nowTs - app.lastDebugPaint > 120) {
        app.lastDebugPaint = nowTs;
        updateDebug();
      }
    } else if (app.debugOpen && nowTs - app.lastDebugPaint > 200) {
      app.lastDebugPaint = nowTs;
      updateDebug();
    }

    requestAnimationFrame(tick);
  }

  function updateChat(node, t) {
    var spec = CHAT_OVERLAYS[node.node_id];
    var shouldShow = !!spec && !app.endingShown && t < spec.until;
    if (shouldShow === app.chatOn) return;
    app.chatOn = shouldShow;
    els.chatOverlay.classList.toggle('is-on', shouldShow);
    els.chatOverlay.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');
  }

  function setChat(on) {
    app.chatOn = !!on;
    els.chatOverlay.classList.toggle('is-on', !!on);
    els.chatOverlay.setAttribute('aria-hidden', on ? 'false' : 'true');
  }

  function now() {
    return typeof performance !== 'undefined' ? performance.now() : Date.now();
  }

  /* ------------------------------------------------------------------ *
   * 调试面板
   * ------------------------------------------------------------------ */

  function toggleDebug(force) {
    var open = typeof force === 'boolean' ? force : !app.debugOpen;
    app.debugOpen = open;
    els.debugPanel.hidden = !open;
    if (open) {
      updateDebug();
      renderDebugPath();
      setTimeout(function () {
        try { els.debugClose.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
      }, 0);
    } else {
      try { els.debugBtn.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
    }
  }

  function renderDebugNodes() {
    els.debugNodeList.replaceChildren();
    app.debugButtons = new Map();
    app.debugFlags = new Map();

    app.nodeOrder.forEach(function (id) {
      var node = app.nodes.get(id);
      if (!node) return;

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'debug-node';
      btn.dataset.nodeId = id;
      btn.title = node.node_type + (node.speaker ? ' · ' + node.speaker : '');

      var idx = document.createElement('span');
      idx.className = 'dn-index';
      idx.textContent = shortLabel(id);

      var name = document.createElement('span');
      name.className = 'dn-id';
      name.textContent = id;

      var flag = document.createElement('span');
      flag.className = 'dn-flag';
      flag.textContent = '?';

      btn.appendChild(idx);
      btn.appendChild(name);
      btn.appendChild(flag);
      btn.addEventListener('click', function () { jumpToNode(id); });

      els.debugNodeList.appendChild(btn);
      app.debugButtons.set(id, btn);
      app.debugFlags.set(id, flag);
    });

    updateDebugNodeFlags();
  }

  function updateDebugNodeFlags() {
    if (!app.debugFlags.size) return;
    app.debugFlags.forEach(function (flag, id) {
      var a = app.availability.get(id);
      flag.classList.remove('is-ok', 'is-missing');
      if (forceMissingAll || FORCE_MISSING.has(id) || a === false) {
        flag.textContent = '缺';
        flag.classList.add('is-missing');
      } else if (a === true) {
        flag.textContent = '✓';
        flag.classList.add('is-ok');
      } else {
        flag.textContent = '?';
      }
    });
    if (app.currentNode && app.debugButtons.has(app.currentNode.node_id)) {
      app.debugButtons.forEach(function (btn, id) {
        btn.classList.toggle('is-current', id === app.currentNode.node_id);
      });
    }
  }

  function updateDebug() {
    if (!app.chapter) return;
    var node = app.currentNode;
    els.dbgState.textContent = app.state;
    els.dbgNode.textContent = node ? node.node_id : '—';
    els.dbgType.textContent = node ? nodeTypeLabel(node.node_type) + ' / ' + node.node_type : '—';

    var t = getPlayhead();
    var d = node ? videoDurationOf(node) : 0;
    var actual = app.currentVideo && Number.isFinite(app.currentVideo.duration)
      ? app.currentVideo.duration
      : null;
    els.dbgTime.textContent = t.toFixed(2) + 's / ' + d + 's' +
      (actual ? ' (file ' + actual.toFixed(2) + 's)' : (app.fallback ? ' (fallback)' : ''));

    if (node && node.interaction) {
      var trig = toNumber(node.interaction.trigger_time_sec);
      var tout = toNumber(node.interaction.timeout_sec);
      els.dbgTrigger.textContent = (trig === null ? '—' : trig) + ' / ' + (tout === null ? '—' : tout);
    } else {
      els.dbgTrigger.textContent = '—';
    }

    els.dbgMode.textContent = advanceMode === 'trigger' ? 'trigger（到点切）' : 'ended（播完切）';
    els.dbgItems.textContent = app.items.size ? Array.from(app.items).map(itemLabel).join('、') : '空';
    els.dbgPathlen.textContent = app.path.length + ' 个节点';
    els.debugAdvance.textContent = '切镜模式：' + (advanceMode === 'trigger' ? 'trigger' : '播完');
    updateDebugNodeFlags();
  }

  function renderDebugPath() {
    if (!els.debugPathList) return;
    els.debugPathList.replaceChildren();
    app.path.forEach(function (entry) {
      var li = document.createElement('li');
      if (entry.option_label) li.classList.add('is-choice');
      var text = shortLabel(entry.node_id) + ' · ' + (entry.speaker || nodeTypeLabel(entry.node_type));
      if (entry.option_label) text += ' → ' + entry.option_label;
      if (entry.via === 'timeout') text += '（超时）';
      li.textContent = text;
      els.debugPathList.appendChild(li);
    });
  }

  function jumpToNode(nodeId) {
    if (!app.nodes.has(nodeId)) {
      showToast('节点不存在：' + nodeId, 'error');
      return;
    }
    if (!app.started) {
      app.started = true;
      els.startScreen.hidden = true;
    }
    if (app.currentVideo) {
      try { app.currentVideo.pause(); } catch (e) { /* ignore */ }
    }
    app.fallback = null;
    app.endingShown = false;
    hideEnding(true);
    showToast('调试跳转 · ' + shortLabel(nodeId));
    enterNode(nodeId, { via: 'debug' });
    if (window.matchMedia && window.matchMedia('(max-width: 760px)').matches) {
      toggleDebug(false);
    }
  }

  /* ------------------------------------------------------------------ *
   * 视频缺失兜底的跳过
   * ------------------------------------------------------------------ */

  function skipFallback() {
    if (!app.fallback) return;
    if (app.state !== 'playing' && app.state !== 'choosing') return;
    var node = app.currentNode;
    if (!node) return;

    if (app.state === 'choosing') {
      resolveDefault('skip');
      return;
    }
    if (node.node_type === 'ending') {
      showEnding(node);
      return;
    }
    if (isChoiceNode(node)) {
      var trigger = toNumber(node.interaction.trigger_time_sec);
      if (trigger !== null && getPlayhead() < trigger) {
        app.fallback.startAt = now() - trigger * 1000;
        app.fallback.duration = Math.max(app.fallback.duration, trigger);
        return;
      }
    }
    advanceNode(node.interaction && node.interaction.default_next_node, { via: 'skip' });
  }

  /* ------------------------------------------------------------------ *
   * 事件绑定
   * ------------------------------------------------------------------ */

  function bindEvents() {
    els.startBtn.addEventListener('click', startRun);
    els.retryBtn.addEventListener('click', function () { window.location.reload(); });

    els.resumeBtn.addEventListener('click', function () {
      hideResumePrompt();
      if (app.currentVideo) {
        var p = app.currentVideo.play();
        if (p && typeof p.catch === 'function') {
          p.catch(function (err) {
            warn('恢复播放失败：', err);
            showResumePrompt();
          });
        }
      }
    });

    els.fallbackSkip.addEventListener('click', skipFallback);
    els.poster.addEventListener('error', function () {
      els.poster.classList.add('is-broken');
    });

    els.debugBtn.addEventListener('click', function () { toggleDebug(); });
    els.debugClose.addEventListener('click', function () { toggleDebug(false); });
    els.debugAdvance.addEventListener('click', function () {
      advanceMode = advanceMode === 'trigger' ? 'ended' : 'trigger';
      showToast('切镜模式：' + (advanceMode === 'trigger' ? 'trigger（到点切）' : 'ended（播完切）'));
      updateDebug();
    });
    els.debugReset.addEventListener('click', function () {
      if (!app.chapter) return;
      if (app.currentVideo) {
        try { app.currentVideo.pause(); } catch (e) { /* ignore */ }
      }
      app.started = true;
      showToast('已重置到 s01');
      resetRun(app.chapter.start_node);
    });
    els.debugClearItems.addEventListener('click', function () {
      app.items.clear();
      renderItems();
      updateDebug();
      showToast('道具已清空');
    });

    els.replayBtn.addEventListener('click', function () {
      hideEnding(true);
      resetRun(app.chapter.start_node);
    });
    els.rewindBtn.addEventListener('click', function () {
      hideEnding(true);
      restartFromFirstChoice();
    });

    document.addEventListener('keydown', handleKeydown);
  }

  function handleKeydown(event) {
    var tag = (event.target && event.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    // ~ / ` 打开调试
    if (event.key === '~' || event.key === '`' || event.code === 'Backquote') {
      event.preventDefault();
      toggleDebug();
      return;
    }

    if (event.key === 'Escape') {
      if (app.debugOpen) {
        event.preventDefault();
        toggleDebug(false);
      }
      return;
    }

    if (app.debugOpen) return;

    if (app.state === 'choosing' && app.choice && !app.choice.resolved) {
      var idx = parseInt(event.key, 10) - 1;
      if (!isNaN(idx) && idx >= 0 && idx < 9) {
        var option = app.choice.options[idx];
        if (option) {
          event.preventDefault();
          selectOption(option, 'keyboard');
          return;
        }
      }
    }

    if (event.code === 'Space' && app.fallback) {
      if (tag === 'BUTTON') return;
      event.preventDefault();
      skipFallback();
    }
  }

  /* ------------------------------------------------------------------ *
   * 只读调试 API（供联调/自动化验收使用）
   * ------------------------------------------------------------------ */

  window.__mvPlayer = Object.freeze({
    get state() { return app.state; },
    get node() { return app.currentNode ? app.currentNode.node_id : null; },
    get path() { return app.path.map(function (e) { return e.node_id; }); },
    get items() { return Array.from(app.items); },
    get advanceMode() { return advanceMode; },
    setAdvanceMode: function (mode) {
      if (ADVANCE_MODES.indexOf(mode) < 0) return false;
      advanceMode = mode;
      updateDebug();
      return true;
    },
    jumpTo: function (nodeId) { jumpToNode(nodeId); return true; },
    chapterUrl: CHAPTER_URL.href
  });

  /* ------------------------------------------------------------------ *
   * 启动
   * ------------------------------------------------------------------ */

  boot();
})();
