"use strict";

/*
 * Behavioural harness for the QCC MV3 human-listener lifecycle
 * (R0.C) and HUMAN_ONLY teaching glue (R1 UI).
 *
 * Extracts the REAL functions/consts from the extension service
 * worker source, runs them in an isolated vm context against a
 * mocked chrome API, and executes ONE scenario per invocation:
 *
 *   node qcc_listener_lifecycle_harness.js <scenario>
 *
 * Exit code 0 == scenario passed.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");
const nodeCrypto = require("crypto");

const SW = path.resolve(
  __dirname,
  "..",
  "..",
  "chrome_extension",
  "qcc",
  "background",
  "service_worker.js"
);

/* The worker is stored with CRLF line endings; normalise for scanning. */
const SOURCE = fs.readFileSync(SW, "utf8").replace(/\r\n?/g, "\n");

const FUNCTIONS = [
  "qccHumanArmStorageKey",
  "pruneExpiredQccHumanListenerArms",
  "persistQccHumanListenerArm",
  "takeQccHumanListenerArm",
  "qccHumanFrameIdFromPath",
  "autoArmDiscoveryHumanListener",
  "qccHumanListenerToken",
  "clearQccHumanListenerArmsFor",
  "armQccHumanClickListeners",
  "qccHumanRenewalAlarmName",
  "qccScheduleHumanListenerRenewal",
  "qccCancelHumanListenerRenewal",
  "qccHumanListenerArmsForTab",
  "qccRetryHumanListenerRenewal",
  "runQccHumanListenerRenewal",
  "qccCaptureFreshRightClickCausalEvidence",
  "forwardQccHumanDomActionSignal",
  "qccAutomaticMainDocumentId",
  "qccTeachableActionTagLabel",
  "qccTeachableFrameLabel",
  "qccDescribeTeachableActionForActiveTab",
  "qccTeachHumanOnlyCurrentTrustedAction",
];

const CONSTS = [
  "QCC_HUMAN_ACTION_BRIDGE_BASE_URL",
  "QCC_HUMAN_LISTENER_TTL_MS",
  "qccHumanListenerArms",
  "QCC_HUMAN_LISTENER_RENEWAL_MARGIN_MS",
  "QCC_HUMAN_LISTENER_RENEWAL_ALARM_PREFIX",
  "QCC_HUMAN_LISTENER_RENEWAL_RETRY_MS",
  "QCC_HUMAN_LISTENER_RENEWAL_MAX_FAILURES",
  "qccHumanRenewalFailures",
  "qccHumanTrustedActionByTab",
  "QCC_HUMAN_TEACHING_WINDOW_MS",
  "QCC_HUMAN_ARM_STORAGE_PREFIX",
  "QCC_HUMAN_POLICY_TEACHING_ACTORS",
];

/*
 * Deterministic extraction of REAL service-worker source.
 *
 * The declaration start is located by an anchored, uniquely matching
 * pattern. The end is the shortest source prefix, ending in the
 * terminator character ("}" for functions, ";" for constants), that
 * the JavaScript engine itself accepts as a complete declaration.
 * No layout assumption (indentation, closing brace at column zero,
 * line endings) is made, and every failure throws loudly.
 */

function compiles(text) {
  try {
    new vm.Script(text);
    return true;
  } catch (_) {
    return false;
  }
}

function braceBalance(text) {
  let balance = 0;

  for (const ch of text) {
    if (ch === "{") {
      balance += 1;
    } else if (ch === "}") {
      balance -= 1;
    }
  }

  return balance;
}

function locateUnique(pattern, label) {
  const matches = Array.from(SOURCE.matchAll(pattern));

  if (matches.length === 0) {
    throw new Error("SYMBOL_NOT_FOUND::" + label);
  }

  if (matches.length > 1) {
    throw new Error("SYMBOL_AMBIGUOUS::" + label);
  }

  return matches[0].index;
}

function sliceDeclaration(start, terminator, label) {
  for (const requireBalance of [true, false]) {
    let position = start;

    for (;;) {
      position = SOURCE.indexOf(terminator, position);

      if (position < 0) {
        break;
      }

      const text = SOURCE.slice(start, position + 1);

      if (
        (!requireBalance || braceBalance(text) === 0)
        && compiles(text)
      ) {
        return text;
      }

      position += 1;
    }
  }

  throw new Error("DECLARATION_END_NOT_FOUND::" + label);
}

function extractFunction(name) {
  const start = locateUnique(
    new RegExp("^(?:async )?function " + name + "\\(", "gm"),
    "function " + name
  );

  return sliceDeclaration(start, "}", "function " + name);
}

function extractConst(name) {
  const start = locateUnique(
    new RegExp("^const " + name + " =", "gm"),
    "const " + name
  );

  return sliceDeclaration(start, ";", "const " + name);
}

/* Every top-level (column zero) binding of the service worker. */
const TOP_LEVEL_NAMES = new Set();

for (const pattern of [
  /^(?:async )?function ([A-Za-z_$][\w$]*)\(/gm,
  /^(?:const|let|var) ([A-Za-z_$][\w$]*)\b/gm,
]) {
  for (const match of SOURCE.matchAll(pattern)) {
    TOP_LEVEL_NAMES.add(match[1]);
  }
}

function unresolvedDependencies(code, available) {
  const stripped = code
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:"'\w])\/\/[^\n]*/g, "$1");

  const parameters = /^[^(]*\(([\s\S]*?)\)\s*\{/.exec(stripped);
  const parameterText = parameters ? parameters[1] : "";

  const missing = new Set();

  for (const match of stripped.matchAll(
    /(^|[^.\w$])([A-Za-z_$][\w$]*)/g
  )) {
    const name = match[2];

    if (!TOP_LEVEL_NAMES.has(name) || available.has(name)) {
      continue;
    }

    const local = new RegExp(
      "\\b(?:const|let|var|function)\\s+" + name + "\\b"
    );

    if (
      local.test(stripped)
      || new RegExp("\\b" + name + "\\b").test(parameterText)
    ) {
      continue;
    }

    missing.add(name);
  }

  return Array.from(missing).sort();
}

const TAB = 7;

function makeEnv() {
  return {
    session: {},
    alarms: {},
    executeCalls: [],
    fetchBodies: [],
    teachBodies: [],
    teachUrls: [],
    submitCalls: 0,
    evidenceSeq: 0,
    currentDoc: "doc-A",
    executeFailuresRemaining: 0,
    autoArm: true,
    noActiveTab: false,
    fetchFails: false,
    teachHttpFails: false,
    teachResponseOk: true,
    teachResponseStatus: 200,
    teachResponseBody: null,
    tabExists: true,
    inspectFails: false,
  };
}

function load(env) {
  const chrome = {
    storage: {
      session: {
        async get(keys) {
          if (keys === null) {
            return Object.assign({}, env.session);
          }

          const out = {};

          for (const key of [].concat(keys)) {
            if (key in env.session) {
              out[key] = env.session[key];
            }
          }

          return out;
        },

        async set(values) {
          Object.assign(env.session, values);
        },

        async remove(keys) {
          for (const key of [].concat(keys)) {
            delete env.session[key];
          }
        },
      },
    },

    scripting: {
      async executeScript(options) {
        env.executeCalls.push(options);

        if (env.executeFailuresRemaining > 0) {
          env.executeFailuresRemaining -= 1;
          throw new Error("EXECUTE_SCRIPT_FAILED");
        }

        return [{
          result: {
            armed: true,
            target_count: options.args[1].length,
          },
        }];
      },
    },

    alarms: {
      create(name, info) {
        env.alarms[name] = info;
        return Promise.resolve();
      },

      clear(name) {
        delete env.alarms[name];
        return Promise.resolve(true);
      },
    },

    tabs: {
      async get(tabId) {
        if (!env.tabExists) {
          throw new Error("TAB_NOT_FOUND");
        }

        return { id: tabId, status: "complete", url: "https://site.test/" };
      },
    },
  };

  const sandbox = {
    console: { debug() {}, log() {}, warn() {} },
    crypto: { randomUUID: () => nodeCrypto.randomUUID() },
    chrome,

    async fetch(url, options) {
      const body = JSON.parse(options.body);
      const target = String(url);

      if (target.endsWith("/human-policy-teaching")) {
        env.teachBodies.push(body);
        env.teachUrls.push(target);

        if (env.teachHttpFails) {
          throw new Error("BRIDGE_HTTP_DOWN");
        }

        return {
          ok: env.teachResponseOk !== false,
          status: env.teachResponseStatus,
          async json() {
            return (
              env.teachResponseBody
              || {
                ok: true,
                status: "CREATED",
                teaching_id: "t-1",
                resulting_restriction: "HUMAN_ONLY",
              }
            );
          },
        };
      }

      if (env.fetchFails) {
        throw new Error("BRIDGE_HTTP_DOWN");
      }

      env.fetchBodies.push(body);

      return {
        ok: true,
        status: 200,
        async json() {
          return { ok: true, accepted: true, event_id: "evt-1" };
        },
      };
    },

    async inspectSpecificTabDom() {
      if (env.inspectFails) {
        throw new Error("INSPECT_FAILED");
      }

      return {
        main_url: "https://site.test/",
        frames: [{ frame_id: 0, document_id: env.currentDoc, result: {} }],
      };
    },

    async qccSubmitAutomaticDomCapture() {
      env.submitCalls += 1;
      env.evidenceSeq += 1;

      return {
        capture_id: "cap-" + env.evidenceSeq,
        human_listener_auto_arm: env.autoArm,
        human_listener_scope_id: "scope-1",
        human_listener_evidence_id: "ev-" + env.evidenceSeq,
        human_listener_plan: {
          targets: [{ selector: "#a", frame_path: "main" }],
        },
      };
    },

    async qccResolveActiveNormalWebTab() {
      if (env.noActiveTab) {
        throw new Error("QCC_ACTIVE_NORMAL_TAB_NOT_FOUND");
      }

      return { id: TAB, url: "https://site.test/" };
    },

    installQccHumanClickListenerInFrame() {
      /* Never actually invoked: chrome.scripting.executeScript is mocked. */
      return { armed: false };
    },
  };

  const context = vm.createContext(sandbox);

  const available = new Set(
    FUNCTIONS.concat(CONSTS).concat(Object.keys(sandbox))
  );

  const pieces = []
    .concat(CONSTS.map(extractConst))
    .concat(FUNCTIONS.map(extractFunction));

  FUNCTIONS.concat(CONSTS).forEach((name, index) => {
    const code = pieces[
      index < FUNCTIONS.length
        ? CONSTS.length + index
        : index - FUNCTIONS.length
    ];

    const missing = unresolvedDependencies(code, available);

    if (missing.length > 0) {
      throw new Error(
        "UNRESOLVED_DEPENDENCIES::" + name + "::" + missing.join(",")
      );
    }
  });

  const exported = FUNCTIONS.concat(CONSTS).join(", ");

  vm.runInContext(
    pieces.join("\n")
      + "\n;globalThis.__api = { " + exported + " };",
    context
  );

  return sandbox.__api;
}

/* ------------------------------------------------------------ */

function backend(env) {
  env.evidenceSeq += 1;

  return {
    capture_id: "cap-" + env.evidenceSeq,
    human_listener_auto_arm: true,
    human_listener_scope_id: "scope-1",
    human_listener_evidence_id: "ev-" + env.evidenceSeq,
    human_listener_plan: {
      targets: [{ selector: "#a", frame_path: "main" }],
    },
  };
}

function capture(env) {
  return {
    main_url: "https://site.test/",
    frames: [{ frame_id: 0, document_id: env.currentDoc, result: {} }],
  };
}

async function armDoc(api, env) {
  return api.autoArmDiscoveryHumanListener(backend(env), TAB, capture(env));
}

function armKeys(env) {
  return Object.keys(env.session).filter(
    (key) => key.startsWith("qcc:human-arm:")
  );
}

function tokenOf(env) {
  const keys = armKeys(env);
  assert.strictEqual(keys.length, 1);
  return keys[0].slice("qcc:human-arm:".length);
}

function signal(token, overrides = {}) {
  return Object.assign(
    {
      listener_token: token,
      selector: "#a",
      frame_path: "main",
      observed_at: "2026-09-19T10:00:00.000Z",
    },
    overrides
  );
}

const SENDER = { tab: { id: TAB }, documentId: "doc-A", frameId: 0 };

async function rejects(promise, text) {
  try {
    await promise;
  } catch (error) {
    assert.ok(
      String(error.message).includes(text),
      "expected " + text + " got " + error.message
    );
    return;
  }

  assert.fail("expected rejection " + text);
}

const SCENARIOS = {
  async renewal_alarm_scheduled_after_arm() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    const names = Object.keys(env.alarms);

    assert.strictEqual(names.length, 1);
    assert.strictEqual(names[0], "qcc:human-renew:" + TAB);

    const expected =
      Date.now()
      + api.QCC_HUMAN_LISTENER_TTL_MS
      - api.QCC_HUMAN_LISTENER_RENEWAL_MARGIN_MS;

    assert.ok(Math.abs(env.alarms[names[0]].when - expected) < 5000);
  },

  async duplicate_arm_cycles_keep_single_alarm() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    await armDoc(api, env);
    await armDoc(api, env);

    assert.strictEqual(Object.keys(env.alarms).length, 1);
  },

  async renewal_not_due_is_noop_and_idempotent() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    const executeBefore = env.executeCalls.length;

    const first = await api.runQccHumanListenerRenewal(TAB);
    const second = await api.runQccHumanListenerRenewal(TAB);

    assert.strictEqual(first.reason, "LISTENER_ALREADY_LIVE");
    assert.strictEqual(second.reason, "LISTENER_ALREADY_LIVE");
    assert.strictEqual(env.executeCalls.length, executeBefore);
    assert.strictEqual(Object.keys(env.alarms).length, 1);
  },

  async renewal_reinstalls_before_expiry() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    const oldToken = tokenOf(env);

    for (const arm of api.qccHumanListenerArms.values()) {
      arm.expires_at = Date.now() + 30 * 1000;
    }

    const executeBefore = env.executeCalls.length;

    const result = await api.runQccHumanListenerRenewal(TAB);

    assert.strictEqual(result.renewed, true);
    assert.strictEqual(result.reason, "RENEWED");
    assert.strictEqual(env.executeCalls.length, executeBefore + 1);

    const call = env.executeCalls[env.executeCalls.length - 1];

    assert.strictEqual(call.target.documentIds.length, 1);
    assert.strictEqual(call.target.documentIds[0], "doc-A");

    const newToken = tokenOf(env);

    assert.notStrictEqual(newToken, oldToken);
    assert.strictEqual(api.qccHumanListenerArms.has(oldToken), false);
  },

  async renewal_document_changed_fails_closed() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    for (const arm of api.qccHumanListenerArms.values()) {
      arm.expires_at = Date.now() + 30 * 1000;
    }

    const executeBefore = env.executeCalls.length;

    env.currentDoc = "doc-B";

    const result = await api.runQccHumanListenerRenewal(TAB);

    assert.strictEqual(result.renewed, false);
    assert.strictEqual(result.reason, "DOCUMENT_CHANGED");
    assert.strictEqual(env.executeCalls.length, executeBefore);
    assert.strictEqual(armKeys(env).length, 0);
    assert.strictEqual(api.qccHumanListenerArms.size, 0);
  },

  async renewal_retries_are_bounded_then_gives_up() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    for (const arm of api.qccHumanListenerArms.values()) {
      arm.expires_at = Date.now() + 30 * 1000;
    }

    env.executeFailuresRemaining = 99;

    let last;

    for (let i = 0; i < api.QCC_HUMAN_LISTENER_RENEWAL_MAX_FAILURES; i += 1) {
      last = await api.runQccHumanListenerRenewal(TAB);
    }

    assert.strictEqual(last.renewed, false);
    assert.strictEqual(last.reason, "RENEWAL_GAVE_UP");
    assert.strictEqual(api.qccHumanRenewalFailures.has(TAB), false);
  },

  async renewal_closed_tab_clears_everything() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    for (const arm of api.qccHumanListenerArms.values()) {
      arm.expires_at = Date.now() + 30 * 1000;
    }

    env.tabExists = false;

    const result = await api.runQccHumanListenerRenewal(TAB);

    assert.strictEqual(result.renewed, false);
    assert.strictEqual(result.reason, "TAB_UNAVAILABLE");
    assert.strictEqual(armKeys(env).length, 0);
    assert.strictEqual(api.qccHumanListenerArms.size, 0);
  },

  async install_failure_leaves_no_stale_storage_arm() {
    const env = makeEnv();
    const api = load(env);

    env.executeFailuresRemaining = 1;

    const result = await armDoc(api, env);

    assert.strictEqual(result.armed, false);
    assert.strictEqual(armKeys(env).length, 0);
    assert.strictEqual(api.qccHumanListenerArms.size, 0);
    assert.strictEqual(Object.keys(env.alarms).length, 0);
  },

  async clear_arms_removes_both_memory_and_storage() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    const token = tokenOf(env);

    await api.clearQccHumanListenerArmsFor(TAB);

    assert.strictEqual(api.qccHumanListenerArms.has(token), false);
    assert.strictEqual(armKeys(env).length, 0);
  },

  async sw_restart_recovers_arm_for_click_via_storage() {
    const env = makeEnv();
    const first = load(env);

    await armDoc(first, env);

    const token = tokenOf(env);

    /*
     * Service Worker restart: a brand-new module load, fresh
     * in-memory Maps, but chrome.storage.session (env.session)
     * survives untouched.
     */
    const restarted = load(env);

    assert.strictEqual(restarted.qccHumanListenerArms.size, 0);

    const result = await restarted.forwardQccHumanDomActionSignal(
      signal(token), SENDER
    );

    assert.strictEqual(result.accepted, true);
  },

  async forward_uses_fresh_evidence_and_is_single_shot() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);

    const token = tokenOf(env);
    const submitBefore = env.submitCalls;

    const result = await api.forwardQccHumanDomActionSignal(
      signal(token), SENDER
    );

    assert.strictEqual(result.accepted, true);
    assert.strictEqual(env.fetchBodies.length, 1);
    assert.ok(env.fetchBodies[0].signal.evidence_id);
    assert.ok(env.submitCalls > submitBefore);

    await rejects(
      api.forwardQccHumanDomActionSignal(signal(token), SENDER),
      "QCC_HUMAN_SIGNAL_ARM_NOT_FOUND"
    );

    assert.strictEqual(env.fetchBodies.length, 1);
  },

  async forward_rejects_wrong_tab_document_frame() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    let token = tokenOf(env);

    await rejects(
      api.forwardQccHumanDomActionSignal(
        signal(token),
        { tab: { id: TAB + 1 }, documentId: "doc-A", frameId: 0 }
      ),
      "QCC_HUMAN_SIGNAL_TAB_MISMATCH"
    );

    await armDoc(api, env);
    token = tokenOf(env);

    await rejects(
      api.forwardQccHumanDomActionSignal(
        signal(token),
        { tab: { id: TAB }, documentId: "doc-WRONG", frameId: 0 }
      ),
      "QCC_HUMAN_SIGNAL_DOCUMENT_MISMATCH"
    );

    await armDoc(api, env);
    token = tokenOf(env);

    await rejects(
      api.forwardQccHumanDomActionSignal(
        signal(token),
        { tab: { id: TAB }, documentId: "doc-A", frameId: 3 }
      ),
      "QCC_HUMAN_SIGNAL_FRAME_MISMATCH"
    );

    assert.strictEqual(env.fetchBodies.length, 0);
  },

  async pointerdown_action_is_never_teachable() {
    const env = makeEnv();
    const api = load(env);

    await api.armQccHumanClickListeners({
      tab_id: TAB,
      session_id: "presentation-1",
      evidence_id: "ev-x",
      event_mode: "POINTERDOWN",
      targets: [{ selector: "#a", frame_path: "main" }],
      frame_documents: [{ frame_id: 0, document_id: "doc-A" }],
    });

    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    assert.strictEqual(api.qccHumanTrustedActionByTab.size, 0);
  },

  async contextmenu_success_becomes_teachable() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    assert.strictEqual(api.qccHumanTrustedActionByTab.has(TAB), true);

    const describe = await api.qccDescribeTeachableActionForActiveTab();

    assert.strictEqual(describe.ok, true);
    assert.strictEqual(describe.available, true);
    assert.strictEqual(typeof describe.label, "string");
    assert.strictEqual(describe.frame_label, "documento principal");
    assert.strictEqual(typeof describe.armed_at, "number");
  },

  async describe_teachable_action_absent_by_default() {
    const env = makeEnv();
    const api = load(env);

    const describe = await api.qccDescribeTeachableActionForActiveTab();

    assert.strictEqual(describe.available, false);
    assert.strictEqual(describe.reason, "NO_TRUSTED_ACTION");
  },

  async describe_teachable_action_absent_without_active_tab() {
    const env = makeEnv();
    const api = load(env);

    env.noActiveTab = true;

    const describe = await api.qccDescribeTeachableActionForActiveTab();

    assert.strictEqual(describe.ok, true);
    assert.strictEqual(describe.available, false);
  },

  async teachable_action_labels_are_generic_and_non_identifying() {
    const env = makeEnv();
    const api = load(env);

    assert.strictEqual(
      api.qccTeachableActionTagLabel('button[onclick="validarYEnviar()"]'),
      "botón"
    );
    assert.strictEqual(
      api.qccTeachableActionTagLabel('a[href="#"]'),
      "enlace"
    );
    assert.strictEqual(
      api.qccTeachableActionTagLabel('input[type="text"]'),
      "campo"
    );
    assert.strictEqual(
      api.qccTeachableActionTagLabel("#weird-id"),
      "elemento"
    );

    assert.strictEqual(api.qccTeachableFrameLabel("main"), "documento principal");
    assert.strictEqual(api.qccTeachableFrameLabel("qcc-frame:1"), "subframe");

    /* Never leaks the literal onclick argument back out. */
    const label = api.qccTeachableActionTagLabel(
      'button[onclick="validarYEnviar(\'INI\')"]'
    );

    assert.ok(!label.includes("INI"));
  },

  async teach_rejects_when_no_trusted_action() {
    const env = makeEnv();
    const api = load(env);

    await rejects(
      api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "SIDE_PANEL"),
      "QCC_TEACH_NO_TRUSTED_ACTION"
    );

    assert.strictEqual(env.teachBodies.length, 0);
  },

  async teach_rejects_unknown_actor() {
    const env = makeEnv();
    const api = load(env);

    await rejects(
      api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "SOMEONE_ELSE"),
      "QCC_TEACH_ACTOR_INVALID"
    );

    assert.strictEqual(env.teachBodies.length, 0);
  },

  async teach_sends_bridge_contract_shape_and_created_response() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    const result = await api.qccTeachHumanOnlyCurrentTrustedAction(
      TAB, "SIDE_PANEL"
    );

    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.status, "CREATED");
    assert.strictEqual(result.resulting_restriction, "HUMAN_ONLY");

    assert.strictEqual(env.teachBodies.length, 1);
    assert.strictEqual(
      env.teachUrls[0],
      "http://127.0.0.1:8766/qcc/session/scope-1/human-policy-teaching"
    );

    const body = env.teachBodies[0];

    assert.deepStrictEqual(
      Object.keys(body).sort(),
      ["protocol_version", "signal", "taught_by"]
    );
    assert.strictEqual(body.protocol_version, 1);
    assert.strictEqual(body.taught_by, "SIDE_PANEL");

    assert.deepStrictEqual(
      Object.keys(body.signal).sort(),
      ["event_id", "evidence_id", "frame_path", "observed_at", "selector"]
    );
    assert.strictEqual(body.signal.selector, "#a");
    assert.strictEqual(body.signal.frame_path, "main");
    assert.ok(body.signal.event_id);
    assert.ok(body.signal.evidence_id);
    assert.ok(body.signal.observed_at);
  },

  async teach_already_taught_response_is_not_an_error() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    env.teachResponseBody = {
      ok: true,
      status: "ALREADY_TAUGHT",
      teaching_id: "t-1",
      resulting_restriction: "HUMAN_ONLY",
    };

    const result = await api.qccTeachHumanOnlyCurrentTrustedAction(
      TAB, "SIDE_PANEL"
    );

    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.status, "ALREADY_TAUGHT");
  },

  async teach_stale_evidence_is_rejected() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    env.teachResponseOk = false;
    env.teachResponseStatus = 409;
    env.teachResponseBody = {
      error: "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ID_NOT_FOUND",
    };

    await rejects(
      api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "SIDE_PANEL"),
      "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ID_NOT_FOUND"
    );
  },

  async teach_bridge_http_down_is_rejected_without_consuming_action() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    env.teachHttpFails = true;

    await rejects(
      api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "SIDE_PANEL"),
      "BRIDGE_HTTP_DOWN"
    );

    /* The trusted action itself is untouched: a retry remains possible. */
    assert.strictEqual(api.qccHumanTrustedActionByTab.has(TAB), true);
  },

  async teach_expired_trusted_action_is_rejected() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    api.qccHumanTrustedActionByTab.get(TAB).expires_at = Date.now() - 1;

    await rejects(
      api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "SIDE_PANEL"),
      "QCC_TEACH_NO_TRUSTED_ACTION"
    );

    assert.strictEqual(api.qccHumanTrustedActionByTab.has(TAB), false);
  },

  async shortcut_and_sidepanel_use_identical_teaching_path() {
    const env = makeEnv();
    const api = load(env);

    await armDoc(api, env);
    const token = tokenOf(env);

    await api.forwardQccHumanDomActionSignal(signal(token), SENDER);

    await api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "SIDE_PANEL");
    await api.qccTeachHumanOnlyCurrentTrustedAction(TAB, "EXTENSION_SHORTCUT");

    assert.strictEqual(env.teachBodies.length, 2);

    const [fromPanel, fromShortcut] = env.teachBodies;

    assert.strictEqual(fromPanel.taught_by, "SIDE_PANEL");
    assert.strictEqual(fromShortcut.taught_by, "EXTENSION_SHORTCUT");

    /* Same identity, same URL, same shape: one shared code path. */
    assert.strictEqual(fromPanel.signal.selector, fromShortcut.signal.selector);
    assert.strictEqual(
      fromPanel.signal.frame_path, fromShortcut.signal.frame_path
    );
    assert.strictEqual(
      fromPanel.signal.evidence_id, fromShortcut.signal.evidence_id
    );
    assert.strictEqual(env.teachUrls[0], env.teachUrls[1]);
  },
};

const name = process.argv[2];

if (!SCENARIOS[name]) {
  console.error("UNKNOWN_SCENARIO::" + name);
  process.exit(2);
}

SCENARIOS[name]().then(
  () => {
    process.stdout.write("OK::" + name + "\n");
  },
  (error) => {
    console.error(error && error.stack ? error.stack : error);
    process.exit(1);
  }
);
