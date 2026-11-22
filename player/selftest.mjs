#!/usr/bin/env node
/**
 * T-015 播放器静态自检（零依赖，可选调用本机 ffprobe）
 *
 * 用法（仓库根目录）：
 *   node player/selftest.mjs
 *
 * 校验：
 *   1. chapter_01.json 可解析，start_node / node_id 唯一 / node_type 合法；
 *   2. 所有 default_next_node 与 options[].next_node 指向真实节点；
 *   3. 从 start_node 可达全部节点，且每个可达节点都能到达至少一个结局；
 *   4. 每条 video_path 与 first_frame_path 真实存在且非空；
 *   5. player/ 四个交付文件存在，index.html 引用了 css/js；
 *   6. player.js 中 getElementById 引用的 id 都存在于 index.html；
 *   7. ffprobe 可用时额外核对 12 条视频的 h264+aac / 分辨率 / 时长。
 *
 * 只读 story/ 与 assets/，不修改任何项目文件。
 */

import { readFileSync, existsSync, statSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const CHAPTER = resolve(ROOT, 'story/03_storyboards/chapter_01.json');

const errors = [];
const warnings = [];
const passes = [];

function ok(label, detail = '') {
  passes.push(detail ? `${label} — ${detail}` : label);
}

function fail(label, detail = '') {
  errors.push(detail ? `${label} — ${detail}` : label);
}

function warn(label, detail = '') {
  warnings.push(detail ? `${label} — ${detail}` : label);
}

function fileInfo(path) {
  if (!existsSync(path)) return null;
  const st = statSync(path);
  if (!st.isFile() || st.size === 0) return null;
  return st;
}

function insideRoot(path) {
  const abs = resolve(path);
  return abs === ROOT || abs.startsWith(ROOT + sep);
}

/* ------------------------------------------------------------------ */
/* 1. 章节 JSON                                                        */
/* ------------------------------------------------------------------ */

let chapter = null;
try {
  chapter = JSON.parse(readFileSync(CHAPTER, 'utf8'));
  ok('章节 JSON 可解析', `story/03_storyboards/chapter_01.json`);
} catch (err) {
  fail('章节 JSON 解析失败', err.message);
}

const NODE_TYPES = new Set(['video_play', 'choice_branch', 'item_discovery', 'qte_event', 'ending']);

if (chapter) {
  if (!chapter.start_node) fail('缺少 start_node');
  if (!Array.isArray(chapter.nodes) || chapter.nodes.length === 0) {
    fail('nodes 为空');
  }
}

const nodes = new Map();
let order = [];
if (chapter && Array.isArray(chapter.nodes)) {
  chapter.nodes.forEach((node, index) => {
    if (!node || typeof node !== 'object') {
      fail(`nodes[${index}] 不是对象`);
      return;
    }
    if (!node.node_id) {
      fail(`nodes[${index}] 缺少 node_id`);
      return;
    }
    if (nodes.has(node.node_id)) fail(`node_id 重复`, node.node_id);
    nodes.set(node.node_id, node);
    order.push(node.node_id);
    if (!NODE_TYPES.has(node.node_type)) {
      fail(`node_type 非法`, `${node.node_id}: ${node.node_type}`);
    }
    if (!node.video || typeof node.video !== 'object') {
      fail(`缺少 video 对象`, node.node_id);
    }
    if (node.node_type === 'ending' && node.interaction) {
      warn(`ending 节点配置了 interaction`, node.node_id);
    }
    if (node.node_type !== 'ending' && !node.interaction) {
      fail(`非 ending 节点缺少 interaction`, node.node_id);
    }
  });
}

if (chapter && chapter.start_node && !nodes.has(chapter.start_node)) {
  fail('start_node 不在节点表中', chapter.start_node);
}

/* ------------------------------------------------------------------ */
/* 2. 分支引用 / 可达性 / 结局可达                                     */
/* ------------------------------------------------------------------ */

const edges = new Map(); // node_id -> [next...]
let optionCount = 0;
let choiceCount = 0;
let endingCount = 0;
const grantedItems = new Set();
const requiredItems = new Set();

if (chapter && nodes.size) {
  for (const [id, node] of nodes) {
    const it = node.interaction || {};
    const nexts = [];
    if (it.default_next_node) nexts.push(it.default_next_node);
    const options = Array.isArray(it.options) ? it.options : [];
    if (options.length) {
      if (node.node_type === 'choice_branch') choiceCount += 1;
      optionCount += options.length;
      const seen = new Set();
      for (const opt of options) {
        if (!opt || !opt.option_id || !opt.label || !opt.next_node) {
          fail('选项字段不完整', `${id}: ${JSON.stringify(opt)}`);
          continue;
        }
        if (seen.has(opt.option_id)) fail('同节点 option_id 重复', `${id}: ${opt.option_id}`);
        seen.add(opt.option_id);
        nexts.push(opt.next_node);
        (opt.grant_items || []).forEach((x) => grantedItems.add(x));
        (opt.required_items || []).forEach((x) => requiredItems.add(x));
      }
    }
    if (node.node_type === 'ending') endingCount += 1;
    edges.set(id, nexts);
  }

  const dangling = [];
  for (const [id, nexts] of edges) {
    for (const next of nexts) {
      if (!nodes.has(next)) dangling.push(`${id} → ${next}`);
    }
  }
  if (dangling.length) fail('存在死链 next_node', dangling.join(', '));
  else ok('所有 next_node 均存在', `${order.length} 节点 / ${choiceCount} 选择点 / ${optionCount} 选项`);

  if (chapter.start_node && nodes.has(chapter.start_node)) {
    const reachable = new Set();
    const queue = [chapter.start_node];
    while (queue.length) {
      const id = queue.shift();
      if (!id || reachable.has(id)) continue;
      reachable.add(id);
      for (const next of edges.get(id) || []) queue.push(next);
    }
    const unreachable = order.filter((id) => !reachable.has(id));
    if (unreachable.length) warn('存在不可达节点', unreachable.join(', '));
    else ok('从 start_node 可达全部节点', `${reachable.size}/${order.length}`);

    const endings = order.filter((id) => nodes.get(id).node_type === 'ending');
    const canReachEnding = new Set(endings);
    let changed = true;
    while (changed) {
      changed = false;
      for (const [id, nexts] of edges) {
        if (canReachEnding.has(id)) continue;
        if (nexts.some((next) => canReachEnding.has(next))) {
          canReachEnding.add(id);
          changed = true;
        }
      }
    }
    const deadEnds = [...reachable].filter((id) => !canReachEnding.has(id));
    if (deadEnds.length) fail('存在到不了结局的节点', deadEnds.join(', '));
    else ok('每个可达节点都能到达结局', `${endings.length} 个结局`);
  }
}

const missingGrant = [...requiredItems].filter((x) => !grantedItems.has(x));
if (missingGrant.length) fail('required_items 缺少发放来源', missingGrant.join(', '));
else if (requiredItems.size) ok('道具闭环覆盖', `${requiredItems.size} 个需求道具均有 grant 来源`);
else ok('道具闭环', '本章无道具（HUD 仍可运行）');

/* ------------------------------------------------------------------ */
/* 3. 资产文件                                                         */
/* ------------------------------------------------------------------ */

let videoOk = 0;
const videoPaths = [];
let frameOk = 0;
let frameTotal = 0;
const missingVideos = [];
const missingFrames = [];
const badPaths = [];

for (const [id, node] of nodes) {
  const video = node.video || {};
  const vp = video.video_path;
  if (!vp) {
    missingVideos.push(`${id}: video_path 为空`);
    continue;
  }
  const abs = resolve(ROOT, vp);
  if (!insideRoot(abs)) {
    badPaths.push(`${id}: ${vp}`);
    continue;
  }
  videoPaths.push({ id, abs, rel: vp });
  if (fileInfo(abs)) videoOk += 1;
  else missingVideos.push(`${id}: ${vp}`);

  const fp = video.first_frame_path;
  frameTotal += 1;
  if (!fp) {
    missingFrames.push(`${id}: first_frame_path 为空`);
  } else {
    const fabs = resolve(ROOT, fp);
    if (!insideRoot(fabs)) badPaths.push(`${id}: ${fp}`);
    else if (fileInfo(fabs)) frameOk += 1;
    else missingFrames.push(`${id}: ${fp}`);
  }
}

if (badPaths.length) fail('资产路径越出仓库根', badPaths.join(', '));
if (missingVideos.length) fail('视频文件缺失', missingVideos.join(', '));
else ok('视频文件齐备', `${videoOk}/${nodes.size}（${videoPaths.length} 条 video_path）`);
if (missingFrames.length) fail('首帧文件缺失', missingFrames.join(', '));
else ok('首帧占位图齐备', `${frameOk}/${frameTotal}`);

/* ------------------------------------------------------------------ */
/* 4. player/ 交付物与静态引用                                          */
/* ------------------------------------------------------------------ */

const PLAYER_FILES = ['index.html', 'player.css', 'player.js', 'README.md'];
const missingPlayerFiles = PLAYER_FILES.filter((name) => !fileInfo(resolve(HERE, name)));
if (missingPlayerFiles.length) fail('player/ 交付文件缺失', missingPlayerFiles.join(', '));
else ok('player/ 交付文件齐备', PLAYER_FILES.join(', '));

let html = '';
let js = '';
let css = '';
try { html = readFileSync(resolve(HERE, 'index.html'), 'utf8'); } catch (e) { /* already reported */ }
try { js = readFileSync(resolve(HERE, 'player.js'), 'utf8'); } catch (e) { /* already reported */ }
try { css = readFileSync(resolve(HERE, 'player.css'), 'utf8'); } catch (e) { /* already reported */ }

if (html) {
  if (!/<link[^>]+href="player\.css"/.test(html)) fail('index.html 未引用 player.css');
  if (!/<script[^>]+src="player\.js"/.test(html)) fail('index.html 未引用 player.js');
  if (!html.includes('id="app"')) fail('index.html 缺少 #app');
  if (!html.includes('7楼业主群') || !html.includes('704 好像出事，已经报警')) {
    fail('index.html 缺少 s08 真实群聊叠层内容');
  }
}

if (js) {
  const states = ['loading', 'playing', 'choosing', 'transitioning', 'ended'];
  const missingStates = states.filter((s) => !js.includes(`'${s}'`));
  if (missingStates.length) fail('player.js 状态机缺少状态', missingStates.join(', '));
  else ok('状态机五态齐备', states.join(' → '));

  if (!js.includes('../story/03_storyboards/chapter_01.json')) {
    fail('player.js 未引用章节 JSON');
  }
  if (!js.includes('ch01_s08_groupchat')) fail('player.js 未针对 s08 挂载群聊叠层');
  if (!js.includes("addEventListener('error'")) warn('未发现视频 error 监听', '请人工确认兜底');

  // 提取 getElementById('x') / $('x')，检查 HTML 中是否存在对应 id
  const ids = new Set();
  const re = /(?:getElementById|\$)\(\s*'([A-Za-z0-9_-]+)'\s*\)/g;
  let match;
  while ((match = re.exec(js)) !== null) ids.add(match[1]);
  const missingIds = [...ids].filter((id) => !new RegExp(`id="${id}"`).test(html));
  if (missingIds.length) fail('player.js 引用了不存在的 HTML id', missingIds.join(', '));
  else ok('player.js ↔ index.html id 对齐', `${ids.size} 个 id`);

  // 离线硬约束：不得加载外部脚本/样式
  const external = /<(?:script|link)[^>]+(?:src|href)="(?:https?:)?\/\//i.test(html);
  if (external) fail('index.html 引用了外部资源', '违反零 CDN 约束');
  else ok('无外部 CDN/脚本依赖');
}

if (css) {
  if (!css.includes('.choice-layer')) fail('player.css 缺少选择面板样式');
  if (!css.includes('@media (max-width: 760px)')) fail('player.css 缺少移动端断点');
  else ok('移动端断点存在', 'max-width: 760px');
}

const noHash = /\.(png|jpe?g|mp4|webm)$/i;
const queryStrings = videoPaths.filter((v) => /[?#]/.test(v.rel));
if (queryStrings.length) warn('video_path 含查询串', queryStrings.map((v) => v.rel).join(', '));
if (videoPaths.some((v) => noHash.test(v.rel) === false)) {
  warn('video_path 扩展名异常', videoPaths.filter((v) => !noHash.test(v.rel)).map((v) => v.rel).join(', '));
}

/* ------------------------------------------------------------------ */
/* 5. ffprobe（可选）                                                  */
/* ------------------------------------------------------------------ */

const ffprobe = spawnSync('ffprobe', ['-version'], { encoding: 'utf8' });
if (ffprobe.error || ffprobe.status !== 0) {
  warn('未找到 ffprobe，跳过视频编码/时长核对');
} else if (videoPaths.length) {
  let probed = 0;
  const bad = [];
  const durations = [];
  for (const item of videoPaths) {
    if (!existsSync(item.abs)) continue;
    const res = spawnSync('ffprobe', [
      '-v', 'error',
      '-show_entries', 'stream=codec_name,codec_type,width,height:format=duration',
      '-of', 'json',
      item.abs
    ], { encoding: 'utf8' });
    if (res.status !== 0) {
      bad.push(`${item.id}: ffprobe 失败`);
      continue;
    }
    let info;
    try { info = JSON.parse(res.stdout); } catch (e) {
      bad.push(`${item.id}: ffprobe JSON 解析失败`);
      continue;
    }
    const streams = info.streams || [];
    const v = streams.find((s) => s.codec_type === 'video');
    const a = streams.find((s) => s.codec_type === 'audio');
    const duration = Number(info.format && info.format.duration);
    if (!v) bad.push(`${item.id}: 无视频流`);
    else {
      if (v.codec_name !== 'h264') bad.push(`${item.id}: 视频编码 ${v.codec_name} ≠ h264`);
      if (v.width !== 832 || v.height !== 480) bad.push(`${item.id}: ${v.width}×${v.height} ≠ 832×480`);
    }
    if (!a) bad.push(`${item.id}: 无音轨`);
    else if (a.codec_name !== 'aac') bad.push(`${item.id}: 音频编码 ${a.codec_name} ≠ aac`);
    if (!Number.isFinite(duration) || duration <= 0) bad.push(`${item.id}: 时长不可读`);
    else durations.push(duration);
    probed += 1;
  }
  if (bad.length) fail('视频编码/时长核对', bad.join('; '));
  else {
    const min = Math.min(...durations).toFixed(2);
    const max = Math.max(...durations).toFixed(2);
    const total = durations.reduce((s, x) => s + x, 0).toFixed(1);
    ok('视频编码/分辨率/时长', `${probed} 条 h264+aac 832×480，${min}–${max}s，合计 ${total}s`);
  }
}

/* ------------------------------------------------------------------ */
/* 6. 汇总                                                             */
/* ------------------------------------------------------------------ */

console.log('');
console.log('《猫眼之后》T-015 播放器静态自检');
console.log('='.repeat(64));
for (const line of passes) console.log('  [通过] ' + line);
for (const line of warnings) console.log('  [警告] ' + line);
for (const line of errors) console.log('  [失败] ' + line);
console.log('='.repeat(64));
console.log(`结果：${errors.length ? 'FAIL' : 'PASS'} — ${passes.length} 项通过 / ${warnings.length} 项警告 / ${errors.length} 项失败`);

if (errors.length) process.exitCode = 1;
