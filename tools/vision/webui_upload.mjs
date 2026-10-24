// One fixed WebUI upload. Runtime owns locks, Job, deadlines and all process/cohort proof.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
export const NODE = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe');
export const PLAYWRIGHT = path.resolve(path.dirname(NODE), '../node_modules/playwright');
export const REFERENCE_IMAGE = path.resolve(ROOT, '../RefImage/48463779.jpeg');
export const REFERENCE_SHA = '1806c40d735545d6852e1d1a90dba9c22f4501e79e9cb5784f93268e2331d699';
export const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const samePath = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
function requireFact(ok, message) { if (!ok) throw new Error(message); }

function privatePath(value, base) {
  requireFact(typeof value === 'string' && path.isAbsolute(value), 'absolute private path required');
  const resolved = path.resolve(value), relative = path.relative(base, resolved);
  requireFact(relative && !relative.startsWith('..') && !path.isAbsolute(relative), 'path outside private area');
  let current = base;
  for (const part of relative.split(path.sep)) {
    current = path.join(current, part);
    if (!fs.existsSync(current)) continue;
    requireFact(!fs.lstatSync(current).isSymbolicLink() && samePath(fs.realpathSync(current), current), 'linked private path refused');
  }
  return resolved;
}

export function validateInput(input) {
  requireFact(input && typeof input === 'object' && !Array.isArray(input), 'input object required');
  requireFact(input.url === 'http://127.0.0.1:18080/', 'fixed loopback URL required');
  requireFact(input.max_tokens === 128 && input.deadline_seconds === 120, 'fixed token/deadline bounds required');
  requireFact(typeof input.prompt === 'string' && input.prompt.trim() === input.prompt && input.prompt.length > 0
              && Buffer.byteLength(input.prompt) <= 8192, 'bounded exact prompt required');
  requireFact(typeof input.browser_exe === 'string' && samePath(input.browser_exe, EDGE)
              && fs.statSync(input.browser_exe).isFile(), 'fixed existing Edge required');
  requireFact(samePath(process.execPath, NODE), 'fixed bundled Node required');
  const temporary = path.join(ROOT, '.vision-tmp');
  requireFact(fs.statSync(temporary).isDirectory() && !fs.lstatSync(temporary).isSymbolicLink(), 'private temporary root required');
  for (const key of ['TEMP', 'TMP']) {
    const value = process.env[key];
    requireFact(typeof value === 'string' && path.isAbsolute(value), 'Node private TEMP/TMP required');
    const target = samePath(value, temporary) ? temporary : privatePath(value, temporary);
    requireFact(fs.statSync(target).isDirectory(), 'Node temporary directory missing');
  }
  const profile = privatePath(input.profile_dir, temporary);
  requireFact(!fs.existsSync(profile) && fs.statSync(path.dirname(profile)).isDirectory(), 'new private profile with existing parent required');
  requireFact(typeof input.image_path === 'string' && path.isAbsolute(input.image_path)
              && samePath(input.image_path, REFERENCE_IMAGE), 'exact selected RefImage path required');
  const image = path.resolve(input.image_path);
  requireFact(!fs.lstatSync(image).isSymbolicLink() && samePath(fs.realpathSync(image), image), 'linked RefImage refused');
  const stat = fs.statSync(image);
  requireFact(stat.isFile() && stat.size > 0 && stat.size <= 20 * 1024 * 1024
              && /\.(png|jpe?g|webp)$/i.test(image), 'bounded image fixture required');
  requireFact(input.image_sha256 === REFERENCE_SHA && sha(fs.readFileSync(image)) === REFERENCE_SHA, 'image hash mismatch');
  return {...input, profile_dir: profile, image_path: image};
}

export function createRequestGate(config, emit, fail) {
  let attempted = 0, sent = 0, accepted = null, stopped = false;
  const deadline = config.deadline_at ?? Date.now() + config.deadline_seconds * 1000;
  return {
    get sent() { return sent; },
    get attempted() { return attempted; },
    get accepted() { return accepted; },
    stop() { stopped = true; },
    async route(route) {
      const request = route.request();
      try {
        const url = new URL(request.url());
        requireFact(url.origin === new URL(config.url).origin && !url.username && !url.password, 'off-origin request refused');
        if (request.method() === 'GET') {
          requireFact(['/', '/health', '/metrics', '/mcp', '/settings'].includes(url.pathname)
                      || url.pathname.startsWith('/web/'), 'unapproved UI read refused');
          return await route.continue();
        }
        attempted++;
        requireFact(!stopped && Date.now() < deadline && sent === 0 && request.method() === 'POST'
                    && url.pathname === '/v1/chat/completions' && !url.search, 'extra or unapproved write refused before send');
        const wire = request.postDataBuffer();
        requireFact(Buffer.isBuffer(wire) && wire.length <= 32 * 1024 * 1024, 'bounded actual POST body required');
        const body = JSON.parse(wire.toString('utf8'));
        requireFact(body.max_tokens === 128 && body.stream === true && body.reasoning_effort === 'none'
                    && body.temperature === 0 && body.seed === 42 && !body.strata_mcp && !body.tools
                    && (body.n === undefined || body.n === 1), 'UI sampling/tools differ from fixed smoke');
        requireFact(Array.isArray(body.messages) && body.messages.length === 1 && body.messages[0].role === 'user', 'fresh one-message chat required');
        const content = body.messages[0].content;
        requireFact(Array.isArray(content) && content.length === 2 && content[0].type === 'text'
                    && content[0].text === config.prompt && content[1].type === 'image_url', 'actual prompt/image content mismatch');
        const imageUrl = content[1].image_url?.url;
        requireFact(typeof imageUrl === 'string' && /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(imageUrl), 'actual selected JPEG required');
        requireFact(sha(Buffer.from(imageUrl.slice(imageUrl.indexOf(',') + 1), 'base64')) === config.image_sha256, 'actual uploaded image hash mismatch');
        accepted = request;
        sent = 1; // Reserve the sole send before the first await, including concurrent routes.
        emit({type: 'generation_request', url: request.url(), method: request.method(), count: sent,
              post_data_json: body, post_data_utf8: wire.toString('utf8'), full_wire_sha256: sha(wire)});
        await route.continue();
      } catch (error) {
        stopped = true;
        try { await route.abort('blockedbyclient'); } finally { fail(error); }
      }
    },
  };
}

export function parseResponse(bytes, status) {
  requireFact(status === 200 && bytes.length <= 4 * 1024 * 1024, 'successful bounded generation response required');
  let content = '', done = 0, finish = null, usage = null;
  for (const line of bytes.toString('utf8').split(/\r?\n/)) {
    if (!line.startsWith('data:')) continue;
    const data = line.slice(5).trim();
    requireFact(done === 0, 'response data after DONE');
    if (data === '[DONE]') { done++; continue; }
    const value = JSON.parse(data);
    requireFact(!value.error && !value.strata_mcp, 'API error/tool response refused');
    for (const choice of value.choices || []) {
      requireFact(!choice.delta?.tool_calls, 'tool calls outside smoke');
      content += choice.delta?.content || '';
      if (choice.finish_reason != null) {
        requireFact(finish === null, 'multiple response terminals');
        finish = choice.finish_reason;
      }
    }
    if (value.usage) usage = value.usage;
  }
  requireFact(done === 1 && ['stop', 'length'].includes(finish) && content.trim(), 'incomplete response or empty answer');
  requireFact(Number.isSafeInteger(usage?.prompt_tokens) && usage.prompt_tokens > 0
              && Number.isSafeInteger(usage?.completion_tokens) && usage.completion_tokens > 0
              && usage.completion_tokens <= 128, 'actual usage missing or outside cap');
  return {content, finish_reason: finish, usage, response_sha256: sha(bytes), response_utf8: bytes.toString('utf8')};
}

export async function runUpload(input, chromium, emit) {
  const config = validateInput(input);
  let context, stage = 'launch', closeReturned = false, gate, passed = false;
  const end = Date.now() + config.deadline_seconds * 1000;
  let rejectFatal;
  const fatal = new Promise((_, reject) => { rejectFatal = reject; });
  fatal.catch(() => {});
  const bounded = async promise => {
    requireFact(Date.now() < end, 'WebUI deadline expired');
    let timer;
    try {
      return await Promise.race([promise, fatal, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('WebUI deadline expired')), Math.max(1, end - Date.now()));
      })]);
    } finally { clearTimeout(timer); }
  };
  try {
    fs.mkdirSync(config.profile_dir);
    const temporary = path.join(config.profile_dir, 'tmp');
    fs.mkdirSync(temporary);
    context = await bounded(chromium.launchPersistentContext(config.profile_dir, {
      executablePath: config.browser_exe, headless: true, serviceWorkers: 'block', acceptDownloads: false,
      args: ['--disable-gpu', '--disable-background-networking', '--disable-component-update', '--no-first-run', '--no-default-browser-check'],
      env: {...process.env, TEMP: temporary, TMP: temporary}, timeout: Math.max(1, end - Date.now()),
    }));
    gate = createRequestGate({...config, deadline_at: end}, emit, rejectFatal);
    await bounded(context.route('**/*', route => gate.route(route)));
    const page = context.pages()[0] || await bounded(context.newPage());
    page.setDefaultTimeout(Math.max(1, end - Date.now()));
    const health = page.waitForResponse(r => new URL(r.url()).pathname === '/health');
    stage = 'navigate';
    await bounded(page.goto(config.url, {waitUntil: 'domcontentloaded'}));
    requireFact((await bounded((await bounded(health)).json())).images === true, 'pending: UI image capability is off');
    stage = 'sampling';
    const settings = page.waitForResponse(r => new URL(r.url()).pathname === '/settings');
    await bounded(page.locator('#sampling-btn').click());
    const shared = await bounded((await bounded(settings)).json());
    requireFact(shared.shared === false, 'pending: shared server sampling must already be off');
    await bounded(page.locator('#s-max').fill('128'));
    await bounded(page.locator('#s-thinking [data-v="none"]').click());
    await bounded(page.locator('#s-temp').press('Home'));
    await bounded(page.locator('#s-seed').fill('42'));
    if (await bounded(page.locator('#s-mcp').isVisible())
        && await bounded(page.locator('#s-mcp').getAttribute('aria-checked')) === 'true') {
      await bounded(page.locator('#s-mcp').click());
    }
    requireFact(await bounded(page.locator('#s-max').inputValue()) === '128'
                && await bounded(page.locator('#s-temp').inputValue()) === '0', 'pending: public UI cannot set exact max/greedy');
    await bounded(page.locator('#s-apply').click());
    stage = 'attachment';
    await bounded(page.locator('#file').setInputFiles(config.image_path));
    await bounded(page.locator('#attachments .chip').waitFor({state: 'visible'}));
    const chip = await bounded(page.locator('#attachments .chip').innerText());
    requireFact(chip.includes(path.basename(config.image_path)), 'attachment filename chip missing');
    emit({type: 'attachment', file_input: '#file', set_input_files_returned: true, selected_files: 1,
          image_path: config.image_path, image_sha256: config.image_sha256,
          preview: {kind: 'filename_chip', text: chip, image_thumbnail: false}});
    await bounded(page.locator('#input').fill(config.prompt));
    const response = page.waitForResponse(r => r.request() === gate.accepted);
    stage = 'generation';
    await bounded(page.locator('#send-btn').click());
    const api = await bounded(response);
    requireFact(await bounded(api.finished()) === null, 'generation transport did not finish successfully');
    const evidence = parseResponse(await bounded(api.body()), api.status());
    await bounded(page.locator('#stop-btn').waitFor({state: 'hidden'}));
    await bounded(page.locator('#chat .st-msg--assistant [data-msg-copy]').waitFor({state: 'visible'}));
    requireFact(await bounded(page.locator('#chat .st-msg--assistant .msg-error').count()) === 0, 'UI reports generation error');
    const text = await bounded(page.locator('#chat .st-msg--assistant .st-bubble').innerText());
    const image = page.locator('#chat .st-msg--user .msg-images img');
    const previewUrl = await bounded(image.getAttribute('src'));
    requireFact(typeof previewUrl === 'string' && previewUrl.startsWith('data:image/')
                && sha(Buffer.from(previewUrl.slice(previewUrl.indexOf(',') + 1), 'base64')) === config.image_sha256,
                'submitted UI image preview mismatch');
    requireFact(text.trim() && gate.sent === 1 && gate.attempted === 1, 'missing UI answer or generation count mismatch');
    emit({type: 'final_answer', text, api_status: api.status(), generation_count: gate.sent,
          user_image_preview_sha256: config.image_sha256, api_response: evidence});
    passed = true;
  } catch (error) {
    emit({type: 'error', stage, message: String(error.message || error),
          generation_count: gate?.sent || 0, attempted_writes: gate?.attempted || 0, cleanup_verified: false});
  } finally {
    gate?.stop();
    if (context) {
      try {
        // Runtime retains Node/browser identities and applies its outer cleanup deadline.
        await context.close(); closeReturned = true;
      } catch (error) {
        passed = false;
        emit({type: 'error', stage: 'close', message: String(error.message || error), cleanup_verified: false});
      }
    }
    emit({type: 'closed', context_close_returned: closeReturned, cleanup_verified: false,
          process_proof_owner: 'runtime', generation_count: gate?.sent || 0});
  }
  return passed;
}

async function main() {
  const emit = event => process.stdout.write(JSON.stringify(event) + '\n');
  try {
    let bytes = 0, source = '';
    for await (const chunk of process.stdin) {
      bytes += chunk.length; requireFact(bytes <= 65536, 'stdin JSON too large'); source += chunk;
    }
    const input = JSON.parse(source);
    validateInput(input); // All path/hash/limit checks precede even the Playwright import.
    requireFact(JSON.parse(fs.readFileSync(path.join(PLAYWRIGHT, 'package.json'), 'utf8')).version === '1.62.1', 'bundled Playwright version mismatch');
    const {chromium} = await import(pathToFileURL(path.join(PLAYWRIGHT, 'index.mjs')).href);
    process.exitCode = await runUpload(input, chromium, emit) ? 0 : 1;
  } catch (error) {
    emit({type: 'error', stage: 'preflight', message: String(error.message || error), generation_count: 0, cleanup_verified: false});
    process.exitCode = 1;
  }
}
if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) await main();
