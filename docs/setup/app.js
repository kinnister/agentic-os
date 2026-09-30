/* Agentic OS setup guides — data-driven role guide.
   Adding a new role = adding one entry to ROLES below; the gallery, guide
   pages, init commands, checklists and progress all derive from it. */
'use strict';
(function () {
  var LS = {
    editor: 'aos-guide-editor',
    os: 'aos-guide-os',
    detail: 'aos-guide-detail',
    checks: 'aos-guide-checks'
  };

  // ── Role registry: add a new role = add one entry here ──
  var ROLES = [
    { id: 'developer', label: 'Developer', longLabel: 'Developers', icon: 'ph-code', guided: false, sdlc: true, gen: true,
      time: '~20–30 min', presets: 'developer', hitl: 'gated-autonomous', orch: 'pipeline',
      tagline: 'Governed pipeline delivery — spec → plan → tested code → review-ready MR, with generated stack agents.',
      note: 'After init, stack writer agents (schema / API / component) are generated for your repo and independently audited before they can run. Blind pre-commit review guards every commit.',
      phrases: [
        { say: '/sdlc-guided add bulk export to reports', get: 'Requirements → spec → plan → tested code → review-ready MR', skill: 'sdlc-guided' },
        { say: 'Verify the feature on this branch', get: 'Build checked against its own requirements', skill: 'acceptance-check' },
        { say: 'Create an MR for this branch', get: 'Review-ready merge request with description', skill: 'mr-submit' },
        { say: '/sdlc-auto', get: 'Pipeline runs; gate-arbiter escalates only on risk', skill: 'gate-arbiter' }
      ],
      skills: [
        { name: 'sdlc-guided', desc: 'Idea or ticket through the full governed pipeline' },
        { name: 'sdlc-brief', desc: 'Run a single scoped task through the pipeline' },
        { name: 'sdlc-auto', desc: 'Autonomous mode — gates resolved by the gate-arbiter' },
        { name: 'gate-runner', desc: 'Lint / type / test gates before hand-off' },
        { name: 'acceptance-check', desc: 'Verify a built feature against requirements' },
        { name: 'mr-submit', desc: 'Draft a review-ready merge request' },
        { name: 'gate-arbiter', desc: 'Resolves judgment gates; escalates on risk flags' }
      ] },
    { id: 'qa', label: 'QA Engineer', longLabel: 'QA Engineers', icon: 'ph-flask', guided: false, sdlc: false,
      time: '~20–30 min', presets: 'qa', hitl: 'strict HITL', orch: 'dispatcher',
      tagline: 'Strict human-in-the-loop test design: case generation, automation authoring and failure triage — tests are recommend-only.',
      note: 'Strict HITL by design: agents author test cases and code and recommend commands — humans and CI run them. Real-ID and existing-coverage gates stop invented test cases.',
      phrases: [
        { say: 'Plan QA coverage for the payments epic', get: 'Risk-ranked test plan', skill: 'qa-scoping' },
        { say: 'Generate test cases for work item 1234', get: 'Cases with real IDs, checked against existing coverage', skill: 'test-case agents' },
        { say: 'Triage the failing login test', get: 'Flaky-or-real verdict via the flaky protocol', skill: 'test-failure-triage' },
        { say: 'Scaffold a QE agent framework for regression triage', get: 'A ready-to-fill agent set from the matching QE blueprint', skill: 'qe-blueprints' },
        { say: 'Turn ticket 872 into requirements', get: 'Structured requirements + open questions', skill: 'story-intake' }
      ],
      skills: [
        { name: 'qa-baseline', desc: 'Scaffold the QA strategy for the repo' },
        { name: 'qa-scoping', desc: 'Plan test coverage for an epic or feature' },
        { name: 'gate-runner', desc: 'Lint / type / test gates before hand-off' },
        { name: 'acceptance-check', desc: 'Verify a built feature against requirements' },
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' },
        { name: 'qe-blueprints', desc: '28 QE methodology blueprints — the authority your QA skills cite' }
      ] },
    { id: 'ba-po', label: 'BA / Product Owner', longLabel: 'Business Analysts & POs', icon: 'ph-note-pencil', guided: true, sdlc: false,
      time: '~45–60 min', presets: 'ba-po + portfolio', hitl: 'gated-autonomous', orch: 'dispatcher',
      tagline: 'Requirements, stories, complexity scoring and portfolio memory — no code-writing agents installed.',
      note: 'The assistant proposes — you approve every ticket or repo change. story-author runs automatically at requirements gates; no slash command needed for daily work.',
      phrases: [
        { say: 'Turn ADO work item 1234 into requirements', get: 'Structured requirements doc + open questions', skill: 'story-intake' },
        { say: 'Draft a user story for bulk export with Given/When/Then AC', get: 'Story + acceptance criteria in team format', skill: 'ba-po preset' },
        { say: 'Is the payments epic too big for one sprint?', get: 'Size/risk score + split recommendation', skill: 'effort-sizing' },
        { say: 'Remember: Q3 scope excludes legacy API', get: 'Saved — next session already knows', skill: 'role-memory' }
      ],
      skills: [
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' },
        { name: 'story-author', desc: 'Resolves ambiguous requirements at gates — runs automatically' },
        { name: 'effort-sizing', desc: 'Story/epic sizing before delivery' },
        { name: 'role-memory', desc: 'Cross-session decisions and context' },
        { name: 'sdlc-runs', desc: 'Pipeline/run visibility (read-only, via portfolio)' },
        { name: 'repo-audit-guides', desc: 'Documentation health check (via portfolio)' }
      ] },
    { id: 'architect', label: 'Architect', longLabel: 'Architects', icon: 'ph-compass', guided: false, sdlc: true, gen: true,
      time: '~20–30 min', presets: 'architect', hitl: 'gated-autonomous', orch: 'dispatcher',
      tagline: 'Governance and instruction quality: agent registry, scorecard spawn gate, generated architecture guides.',
      note: 'The instruction-auditor scores every agent contract against the quality rubric before it can be spawned; stack guides are generated from live repo discovery, not guessed.',
      phrases: [
        { say: 'Audit project guides for stale content', get: 'Knowledge-health report with a fix list', skill: 'repo-audit-guides' },
        { say: 'Generate architecture guides for this stack', get: 'Evidence-grounded stack guides', skill: 'repo-guides' },
        { say: 'Remember: orders service standardizes on event sourcing', get: 'Decision recorded across sessions', skill: 'role-memory' },
        { say: '/sdlc-guided refactor the auth module', get: 'Governed pipeline with instruction-quality gates', skill: 'sdlc-guided' }
      ],
      skills: [
        { name: 'repo-audit-guides', desc: 'Documentation & knowledge health check' },
        { name: 'repo-guides', desc: 'Generate stack / architecture guides' },
        { name: 'role-memory', desc: 'Cross-session decisions and context' },
        { name: 'sdlc-guided', desc: 'Idea or ticket through the full governed pipeline' },
        { name: 'gate-arbiter', desc: 'Resolves judgment gates; escalates on risk flags' }
      ] },
    { id: 'devops', label: 'DevOps', longLabel: 'DevOps Engineers', icon: 'ph-git-branch', guided: false, sdlc: true,
      time: '~20–30 min', presets: 'devops', hitl: 'gated-autonomous', orch: 'dispatcher',
      tagline: 'Git hooks, quality gates, PR pipeline gate, MR monitoring and read-only incident triage — no code-writing agents.',
      note: 'Installs the git-hook layer (blind pre-commit review) plus the PR pipeline gate, security reviewer and incident-triage agent. sdlc-preflight is your health check for the whole SDLC layer.',
      phrases: [
        { say: "What's the status of the last pipeline run?", get: 'Run/pipeline health across the repo, read-only', skill: 'sdlc-runs' },
        { say: 'Triage the checkout latency incident', get: '3 ranked hypotheses + cheapest read-only next diagnostic', skill: 'incident-triage' },
        { say: 'Watch MR 42 and report CI failures', get: 'Pipeline monitored, breakage reported', skill: 'mr-watch' },
        { say: 'Create an MR for this branch', get: 'Review-ready merge request', skill: 'mr-submit' },
        { say: 'Run the SDLC doctor', get: 'Health report → .agentic/agentic-sdlc/doctor.json', skill: 'sdlc-preflight' },
        { say: 'Export this run to our observability backend', get: 'Redacted NDJSON sent to a declared profile (e.g. Axiom); no-op until configured', skill: 'telemetry-export' }
      ],
      skills: [
        { name: 'sdlc-runs', desc: 'Pipeline/run visibility (read-only)' },
        { name: 'sdlc-preflight', desc: 'Health check for the SDLC layer' },
        { name: 'mr-watch', desc: 'Monitor MR pipelines, report CI failures' },
        { name: 'mr-submit', desc: 'Draft a review-ready merge request' },
        { name: 'gate-runner', desc: 'Lint / type / test gates before hand-off' },
        { name: 'acceptance-check', desc: 'Verify a built feature against requirements' },
        { name: 'telemetry-export', desc: 'Send run governance telemetry to Axiom/OTLP (opt-in, deny-by-default fields)' }
      ] },
    { id: 'pm-delivery', label: 'PM / Delivery', longLabel: 'PM & Delivery Managers', icon: 'ph-kanban', guided: true, sdlc: false,
      time: '~45–60 min', presets: 'pm-delivery', hitl: 'gated-autonomous', orch: 'dispatcher',
      tagline: 'Ticket & MR adapters, PR pipeline gate and status conventions for delivery management.',
      note: 'No git-hook layer, no code-writing agents. Ticket and MR adapters are configured after init — your dev lead wires them in .agentic/guides/project.md.',
      phrases: [
        { say: "What's the status of open pipelines?", get: 'Read-only run/pipeline health', skill: 'sdlc-runs' },
        { say: 'Turn this ticket into requirements', get: 'Structured requirements + open questions', skill: 'story-intake' },
        { say: 'Watch MR 42 and tell me when CI is green', get: 'Monitoring with status conventions', skill: 'mr-watch' },
        { say: 'Create an MR for this branch', get: 'Review-ready merge request', skill: 'mr-submit' }
      ],
      skills: [
        { name: 'mr-submit', desc: 'Draft a review-ready merge request' },
        { name: 'mr-watch', desc: 'Monitor MR pipelines, report CI failures' },
        { name: 'sdlc-runs', desc: 'Pipeline/run visibility (read-only)' },
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' }
      ] },
    { id: 'security', label: 'Security Engineer', longLabel: 'Security Engineers', icon: 'ph-shield-check', guided: false, sdlc: false,
      time: '~20–30 min', presets: 'security', hitl: 'strict HITL', orch: 'dispatcher',
      tagline: 'DFD-first STRIDE threat modeling with proposed-only severities — writes only docs/security/, no code-writing agents.',
      note: 'Installs the threat-modeler (doc-writer scoped to docs/security/), the code-level security reviewer, and dispatcher routing. Severities always land as proposed — you confirm them.',
      phrases: [
        { say: 'Threat-model the checkout service', get: 'DFD (≥2 trust boundaries) + 8–15 STRIDE threats + risk register + mitigations', skill: 'threat-modeler' },
        { say: 'Finalize the severities', get: 'Refusal — severities stay proposed until you confirm each row', skill: 'threat-modeler' },
        { say: 'Review this PR diff for injection bugs', get: 'Routed to the code-level security reviewer', skill: 'security-reviewer' },
        { say: 'Turn this compliance note into requirements', get: 'Structured requirements doc', skill: 'story-intake' }
      ],
      skills: [
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' },
        { name: 'role-memory', desc: 'Durable per-role memory across sessions' }
      ] },
    { id: 'data', label: 'Data Engineer', longLabel: 'Data Engineers', icon: 'ph-database', guided: false, sdlc: false,
      time: '~20–30 min', presets: 'data', hitl: 'strict HITL', orch: 'dispatcher',
      tagline: 'Layered pipeline design with counted row math and force-tested DQ checks — writes only docs/data/, recommend-only queries.',
      note: 'Installs the pipeline-designer (doc-writer scoped to docs/data/) and dispatcher routing. Classifications always land as proposed — you confirm them; verification queries are handed to you or CI to run.',
      phrases: [
        { say: 'Design the orders ingest pipeline', get: 'Layer diagram + row-math equations + DQ test plans + lineage map', skill: 'pipeline-designer' },
        { say: 'All checks passed first run — mark them verified', get: 'Refusal — a check that has never failed has never been tested', skill: 'pipeline-designer' },
        { say: 'Tag the customer table PII', get: 'Proposed-only classification, escalated for your confirmation', skill: 'pipeline-designer' },
        { say: 'Turn this data request into requirements', get: 'Structured requirements doc', skill: 'story-intake' }
      ],
      skills: [
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' },
        { name: 'role-memory', desc: 'Durable per-role memory across sessions' }
      ] },
    { id: 'design', label: 'Designer / UX', longLabel: 'Designers & UX Researchers', icon: 'ph-pen-nib', guided: false, sdlc: false,
      time: '~20–30 min', presets: 'design', hitl: 'strict HITL', orch: 'dispatcher',
      tagline: 'Emotion-annotated journeys, decision-closing workshops and agent-ready handoffs — writes only docs/design/.',
      note: 'Installs the experience-designer (doc-writer scoped to docs/design/) and dispatcher routing. Decisions always land as proposed — you confirm them; negative ACs are carried verbatim into the handoff.',
      phrases: [
        { say: 'Map the checkout journey', get: 'Journey map with an emotion entry per step', skill: 'experience-designer' },
        { say: 'Log the workshop — no decisions yet', get: 'Refusal — a workshop that closes no decision was a meeting', skill: 'experience-designer' },
        { say: 'Prepare the design handoff', get: 'context.md + spec.md pair, spec cites only recorded decisions', skill: 'experience-designer' },
        { say: 'Turn the framing into a story', get: 'Story with testable acceptance criteria', skill: 'story-author' }
      ],
      skills: [
        { name: 'story-author', desc: 'Raw idea → story with testable AC' },
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' },
        { name: 'role-memory', desc: 'Durable per-role memory across sessions' }
      ] },
    { id: 'portfolio', label: 'Portfolio / Program', longLabel: 'Portfolio & Program Managers', icon: 'ph-chart-line-up', guided: true, sdlc: false,
      time: '~45–60 min', presets: 'portfolio', hitl: 'gated-autonomous', orch: 'dispatcher',
      tagline: 'Run status, knowledge health and durable cross-session memory — read/report-only, no git layer.',
      note: 'Read/report-only: no git hooks, no code-writing agents. Works without MCP — paste a table, attach a CSV, share a screenshot or a Power BI finding.',
      phrases: [
        { say: 'Turn this Power BI insight into a customer-ready requirement', get: 'Structured requirement, customer-ready wording', skill: 'story-intake' },
        { say: 'Convert this Excel analysis into acceptance criteria', get: 'Acceptance criteria in team format', skill: 'story-intake' },
        { say: 'Remember: Q3 scope excludes the legacy API', get: 'Saved — next session already knows', skill: 'role-memory' },
        { say: 'Audit project guides for stale content', get: 'Knowledge-health report', skill: 'repo-audit-guides' }
      ],
      skills: [
        { name: 'sdlc-runs', desc: 'Pipeline/run visibility (read-only)' },
        { name: 'repo-audit-guides', desc: 'Documentation & knowledge health check' },
        { name: 'role-memory', desc: 'Cross-session decisions and context' },
        { name: 'story-intake', desc: 'Idea or ticket → structured requirements' }
      ] }
  ];

  var state = {
    view: location.hash.replace('#', '') || 'home',
    editor: localStorage.getItem(LS.editor) || 'cursor',
    os: localStorage.getItem(LS.os) || 'win',
    detailOv: {},
    checks: {}
  };
  try {
    state.checks = JSON.parse(localStorage.getItem(LS.checks) || '{}');
    state.detailOv = JSON.parse(localStorage.getItem(LS.detail) || '{}');
  } catch (e) { /* corrupted storage falls back to empty state */ }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function initCmd(r) {
    var p = r.id === 'ba-po' ? 'ba-po,portfolio' : r.id;
    return '/agentic-init --presets ' + p + ' --defaults';
  }

  function checklistFor(r, editor, checks) {
    var ed = editor === 'cursor' ? 'Cursor' : 'Claude Code';
    var items = [
      { step: 1, k: 'editor', label: ed + ' installed (app opens)' },
      { step: 1, k: 'git', label: 'Git installed — git --version answers' },
      { step: 1, k: 'python', label: 'Python 3.10+ installed — enforcement hooks and the installer need it' },
      { step: 1, k: 'node', label: 'Node.js LTS installed' },
      editor === 'cursor'
        ? { step: 2, k: 'mkt', label: 'Custom marketplace added (URL ends in .git)' }
        : { step: 2, k: 'mkt', label: 'agentic-os marketplace added (/plugin marketplace add)' },
      { step: 2, k: 'plug1', label: 'agentic-os plugin installed' },
      { step: 2, k: 'plug2', label: 'Agentic SDLC plugin installed' },
      { step: 2, k: 'sp', label: 'Superpowers ≥ 6.1.0 installed' },
      editor === 'cursor'
        ? { step: 2, k: 'reload', label: 'Window reloaded — all three plugin cards visible' }
        : { step: 2, k: 'reload', label: 'Session restarted — plugins active' },
      { step: 3, k: 'repo', label: 'Team repo opened (git status works)' },
      { step: 3, k: 'init', label: initCmd(r) + ' run' },
      { step: 3, k: 'doctor', label: '/agentic-doctor → passed: true' }
    ];
    if (r.sdlc) items.push({ step: 3, k: 'sdlcdoc', label: 'sdlc-preflight → passed: true (before pipeline skills)' });
    return items.map(function (it) {
      var done = !!checks[r.id + ':' + it.k];
      return Object.assign({}, it, { done: done });
    });
  }

  function stepStatus(items, step) {
    var s = items.filter(function (i) { return i.step === step; });
    var d = s.filter(function (i) { return i.done; }).length;
    return d === s.length ? 'done ✓' : d + ' of ' + s.length + ' done';
  }

  function troublesFor(editor) {
    var cursor = [
      { sym: 'Cannot find agentic-os in Browse Marketplace search', fix: 'Expected — it is a custom marketplace. Add it by URL, then install from the User tab.' },
      { sym: 'Marketplace added but no plugin cards', fix: 'You registered the repo but did not Install each plugin. Install both, then reload.' },
      { sym: 'Hundreds of skills listed, can’t find agentic-init', fix: 'That’s the flat Rules/Skills list, not the install view. Open Customize → Plugins.' },
      { sym: 'Used the GitHub browser URL', fix: 'The marketplace URL must end in .git: https://github.com/kinnister/agentic-os.git' }
    ];
    var claude = [
      { sym: '/plugin marketplace add fails', fix: 'Check GitHub access; or clone locally and add the absolute path instead.' },
      { sym: 'Skills missing after install', fix: 'Restart the session — Claude Code activates plugins at session start.' }
    ];
    var shared = [
      { sym: '/agentic-init not recognized', fix: editor === 'cursor' ? 'Plugins not loaded — Developer: Reload Window; confirm both plugin cards.' : 'Restart the session; confirm both plugins installed.' },
      { sym: 'Doctor fails on superpowers', fix: 'Install Superpowers ≥ 6.1.0, then reload/restart.' },
      { sym: 'Doctor fails on node', fix: 'Install Node.js LTS; node --version must answer in a terminal.' },
      { sym: 'Ran init in the wrong folder', fix: 'Never equip the agentic-os marketplace clone — open your team repo and re-run.' }
    ];
    return (editor === 'cursor' ? cursor : claude).concat(shared);
  }

  function phasesFor(r) {
    var phases = [
      { icon: 'ph-magnifying-glass', name: 'Preflight', desc: 'Confirms this is a git repo, python3 and the plugins are present, then discovers your stack — a marker check first, confirmed against the real repo.' },
      { icon: 'ph-chats-circle', name: 'Interview', desc: '--defaults accepts every detected answer for your preset. Without it you get six short screens: roles, HITL dial, autonomy, stack confirm, MCP (connect now / later / without), adapters.' },
      { icon: 'ph-package', name: 'Dependency check', desc: 'Verifies agentic-sdlc and superpowers ≥ 6.1.0 are registered; prints a restart notice for any that are missing.' },
      { icon: 'ph-files', name: 'Scaffold', desc: 'Writes .agentic/ (guides, policies, install journal) and marker-delimited blocks in CLAUDE.md / AGENTS.md. Nothing is committed — the working tree is yours to review.' }
    ];
    if (r.gen) phases.push({ icon: 'ph-robot', name: 'Generate', desc: 'Spawns per-slot subagents for your stack (schema / API / component writers, stack guides) — each audited against the instruction-quality rubric before it is armed.' });
    phases.push({ icon: 'ph-stethoscope', name: 'Doctor', desc: '/agentic-doctor runs 8 checks — file manifest vs journal, hook compilation, canned-event dry-runs, a 3-part HITL smoke test, settings, git hook + dependencies, scorecard, registry — and writes .agentic/agentic-os/doctor.json.' });
    return phases;
  }

  function toolsFor(editor, os) {
    var isWin = os === 'win';
    return [
      { n: '1', name: editor === 'cursor' ? 'Cursor' : 'Claude Code',
        hint: editor === 'cursor' ? (isWin ? 'Run the installer, then open the app' : 'Drag Cursor into Applications, then open it') : 'Follow the install page, then open a terminal',
        check: editor === 'cursor' ? 'no command — just open it once' : 'claude --version',
        url: editor === 'cursor' ? 'https://cursor.com/download' : 'https://claude.com/claude-code',
        why: 'This is where you’ll actually work — the AI editor the plugins install into. Every other tool on this list exists to support it.' },
      { n: '2', name: 'Git', hint: isWin ? 'Keep every default the installer suggests' : 'Accept the Xcode command-line tools if prompted',
        check: 'git --version', url: isWin ? 'https://git-scm.com/download/win' : 'https://git-scm.com/download/mac',
        why: 'Version control — the safety net. The guardrails guarantee nothing changes without a diff you can review, and that only works inside a git repository.' },
      { n: '3', name: 'Python 3.10+', hint: isWin ? 'Tick “Add Python to PATH” on the first screen' : 'Run the .pkg installer — the Python 3.9 that ships with macOS is too old',
        check: isWin ? 'python --version' : 'python3 --version', url: 'https://www.python.org/downloads/',
        why: 'The enforcement hooks — the actual guardrails, not just prompts — are small Python scripts, and the installer runtime needs Python 3.10 or newer. No Python, no enforcement.' },
      { n: '4', name: 'Node.js LTS', hint: 'Pick the LTS build', check: 'node --version', url: 'https://nodejs.org/en/download/',
        why: 'The SDLC health check (sdlc-preflight) runs on Node. One install; you’ll never touch it directly again.' }
    ];
  }

  function decorate(r) {
    var its = checklistFor(r, state.editor, state.checks);
    var d = its.filter(function (i) { return i.done; }).length;
    return Object.assign({}, r, {
      href: '#' + r.id,
      levelLabel: r.guided ? 'Guided setup' : 'Quick setup',
      levelTagClass: r.guided ? 'tag-accent' : 'tag-neutral',
      presetLabel: r.presets,
      presetPlural: r.presets.indexOf('+') > -1 ? 's' : '',
      initCmd: initCmd(r),
      hitlLabel: r.hitl === 'strict HITL' ? 'strict — you approve every step' : 'gated — pauses for risky decisions',
      orchLabel: r.orch === 'pipeline' ? 'staged pipeline' : 'dispatcher-routed',
      started: d > 0,
      done: d,
      total: its.length,
      progressLabel: d === its.length ? 'set up ✓' : 'resume — ' + d + '/' + its.length,
      progressPct: Math.round(d / its.length * 100)
    });
  }

  // ── shared fragments ──
  var RULE_ROW = 'background:linear-gradient(to right, transparent, color-mix(in srgb, var(--color-text) 8%, transparent) 48px, color-mix(in srgb, var(--color-text) 8%, transparent) calc(100% - 48px), transparent) no-repeat bottom / 100% 1px';
  var CMD_BOX = 'display:flex;align-items:center;gap:10px;background:var(--color-neutral-900);border-radius:8px;padding:10px 14px';
  var CMD_CODE = 'flex:1;min-width:200px;font-family:ui-monospace,monospace;font-size:12.5px;color:var(--color-neutral-200);word-break:break-all';

  function copyBtn(cmd, label) {
    return '<button type="button" class="btn btn-ghost" data-cmd="' + esc(cmd) + '" style="font-size:12px"><i class="ph ph-copy"></i>' + (label ? ' ' + label : '') + '</button>';
  }
  function cmdBox(cmd, label) {
    return '<div style="' + CMD_BOX + '"><code style="' + CMD_CODE + '">' + esc(cmd) + '</code>' + copyBtn(cmd, label) + '</div>';
  }
  function segBtn(action, val, on, inner, title) {
    return '<button type="button" class="seg-btn' + (on ? ' on' : '') + '" aria-pressed="' + on + '" data-action="' + action + '" data-val="' + val + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + inner + '</button>';
  }
  function checkRow(roleId, item) {
    return '<label class="check-label" style="display:flex;align-items:flex-start;gap:10px;padding:7px 0;cursor:pointer;font-size:13px;' + RULE_ROW + '">' +
      '<input type="checkbox"' + (item.done ? ' checked' : '') + ' data-key="' + esc(item.k) + '" style="margin-top:2px;accent-color:var(--color-accent);width:15px;height:15px;cursor:pointer">' +
      '<span' + (item.done ? ' class="done"' : '') + '>' + esc(item.label) + '</span></label>';
  }
  function checkSection(roleId, items) {
    return '<div style="margin-top:4px;display:flex;flex-direction:column">' +
      '<div class="card-kicker" style="margin-bottom:2px">Check off as you go</div>' +
      items.map(function (i) { return checkRow(roleId, i); }).join('') + '</div>';
  }

  // ── views ──
  function renderHome() {
    var cards = ROLES.map(decorate).map(function (role) {
      var progress = role.started
        ? '<div style="display:flex;align-items:center;gap:8px;margin-top:2px">' +
          '<div style="flex:1;height:3px;border-radius:2px;background:var(--color-neutral-800);overflow:hidden"><div style="height:100%;width:' + role.progressPct + '%;background:var(--color-accent);border-radius:2px"></div></div>' +
          '<span style="font-size:11px;color:var(--color-accent-300);flex:none">' + esc(role.progressLabel) + '</span></div>'
        : '';
      return '<a href="' + role.href + '" class="card elev-sm role-card" style="text-decoration:none;color:inherit;gap:10px;padding:18px">' +
        '<div style="display:flex;align-items:center;justify-content:space-between">' +
        '<span style="width:34px;height:34px;border-radius:9px;background:var(--color-accent-900);color:var(--color-accent-300);display:inline-flex;align-items:center;justify-content:center"><i class="ph ' + role.icon + '" style="font-size:18px"></i></span>' +
        '<span class="tag ' + role.levelTagClass + '">' + esc(role.levelLabel) + '</span></div>' +
        '<div class="card-title">' + esc(role.label) + '</div>' +
        '<p class="card-body">' + esc(role.tagline) + '</p>' +
        '<div class="card-meta"><i class="ph ph-package"></i> ' + esc(role.presetLabel) + ' <span style="opacity:0.5">·</span> <i class="ph ph-clock"></i> ' + esc(role.time) + '</div>' +
        progress + '</a>';
    }).join('');

    function chip(icon, text, accent) {
      return '<div style="display:inline-flex;align-items:center;gap:8px;border:1px solid ' + (accent ? 'var(--color-accent)' : 'var(--color-divider)') + ';border-radius:8px;padding:8px 14px;' + (accent ? 'color:var(--color-accent)' : 'background:var(--color-surface)') + ';font-size:13px"><i class="ph ' + icon + '"' + (accent ? '' : ' style="color:var(--color-accent)"') + '></i> ' + text + '</div>';
    }
    var arrow = '<i class="ph ph-arrow-right text-muted"></i>';

    function layerRow(n, name, desc) {
      return '<div style="display:grid;grid-template-columns:28px 130px 1fr;gap:12px;align-items:center;border:1px solid color-mix(in srgb, var(--color-section-ghost) 60%, transparent);border-radius:8px;padding:10px 14px;background:color-mix(in srgb, var(--color-section-ghost) 22%, transparent)">' +
        '<span style="width:24px;height:24px;border-radius:7px;border:1px solid var(--color-accent-300);color:var(--color-accent-200);display:inline-flex;align-items:center;justify-content:center;font-size:12px">' + n + '</span>' +
        '<strong style="font-size:13px;font-weight:500">' + name + '</strong>' +
        '<span style="font-size:12.5px;color:color-mix(in srgb, var(--color-text) 70%, transparent)">' + desc + '</span></div>';
    }

    return '<main style="max-width:1060px;margin:0 auto;padding:40px 22px 70px">' +
      '<div style="max-width:660px">' +
      '<h6 style="color:var(--color-accent);margin-bottom:12px">Setup guides</h6>' +
      '<h1 style="margin-bottom:14px">Set up Agentic OS for your role</h1>' +
      '<p class="text-muted" style="font-size:16px;max-width:560px">Governed AI inside Cursor or Claude Code — the same guardrails, tuned to what you do. Pick your role: technical roles get terse steps, everyone else gets a guided walk-through. Nothing is ever committed or pushed without your approval.</p></div>' +

      '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:30px 0 8px">' +
      chip('ph-chat-circle-text', 'You ask in chat') + arrow +
      chip('ph-sparkle', 'A skill runs') + arrow +
      chip('ph-shield-check', 'Governance gates check') + arrow +
      chip('ph-hand-palm', 'You approve', true) + '</div>' +

      '<hr class="hr" style="margin:34px 0">' +

      '<div style="display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap">' +
      '<h3 style="margin:0">Pick your role</h3>' +
      '<span class="text-muted" style="font-size:13px;display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap"><span style="width:8px;height:8px;border-radius:50%;background:var(--color-neutral-500);flex:none"></span>Quick setup — terse steps<span style="opacity:0.5;margin:0 2px">·</span><span style="width:8px;height:8px;border-radius:50%;background:var(--color-accent);flex:none"></span>Guided setup — every click spelled out. Switchable inside.</span></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;margin-top:18px">' + cards + '</div>' +

      '<a href="#mcp" class="card elev-sm banner-card" style="text-decoration:none;color:inherit;flex-direction:row;align-items:center;gap:16px;margin-top:14px;padding:18px;border:1px solid var(--color-accent-800)">' +
      '<span style="width:34px;height:34px;flex:none;border-radius:9px;background:var(--color-accent-900);color:var(--color-accent-300);display:inline-flex;align-items:center;justify-content:center"><i class="ph ph-plugs-connected" style="font-size:18px"></i></span>' +
      '<div style="flex:1;min-width:220px"><div class="card-title">Not using Cursor or Claude Code?</div>' +
      '<p class="card-body" style="margin-top:2px">The same methodology is a published MCP server — search docs, list presets, plan an install from any MCP-capable assistant. Read-only.</p></div>' +
      '<span class="btn btn-ghost" style="flex:none">MCP guide <i class="ph ph-arrow-right"></i></span></a>' +

      '<hr class="hr" style="margin:36px 0">' +

      '<div style="background:linear-gradient(135deg, var(--color-section), var(--color-section-glow));border-radius:var(--radius-lg);padding:26px 28px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px">' +
      '<div><h4 style="margin-bottom:10px">Every role installs the same three layers</h4>' +
      '<p style="font-size:13px;max-width:420px;color:color-mix(in srgb, var(--color-text) 70%, transparent)">Only the last layer differs — your role’s preset decides which skills, agents and guardrails land in the project.</p></div>' +
      '<div style="display:flex;flex-direction:column;gap:8px">' +
      layerRow('1', 'Laptop tools', 'Editor, Git, Python 3, Node.js — once per machine') +
      layerRow('2', 'Editor plugins', 'agentic-os · Agentic SDLC · Superpowers ≥ 6.1.0 — once per editor') +
      layerRow('3', 'Project equip', '/agentic-init with your role’s preset — ~2 min per repo') +
      '</div></div>' +

      '<div class="card" style="margin-top:36px;flex-direction:row;gap:14px;align-items:flex-start;border:1px dashed var(--color-divider);background:transparent">' +
      '<i class="ph ph-plus-circle" style="color:var(--color-accent);font-size:18px;margin-top:1px"></i>' +
      '<p class="text-muted" style="margin:0;font-size:13px"><strong style="color:var(--color-text);font-weight:500">Adding a new role?</strong> This guide is data-driven — each role is one entry (name, preset, phrases, skills). When a new preset lands in <code style="font-family:ui-monospace,monospace;font-size:12px">presets/roles/</code>, add its entry and the gallery, steps and checklist extend themselves.</p></div>' +
      '</main>';
  }

  function renderRole(cur) {
    var effGuided = state.detailOv[cur.id] !== undefined ? state.detailOv[cur.id] : cur.guided;
    var isCursor = state.editor === 'cursor';
    var isWin = state.os === 'win';
    var checklist = checklistFor(cur, state.editor, state.checks);
    var doneCount = checklist.filter(function (i) { return i.done; }).length;
    var allDone = checklist.length > 0 && doneCount === checklist.length;
    var d = decorate(cur);
    var editorName = isCursor ? 'Cursor' : 'Claude Code';
    var chatPanelName = isCursor ? 'Agent chat panel (sidebar)' : 'chat prompt';
    var pct = checklist.length ? Math.round(doneCount / checklist.length * 100) : 0;

    var phraseCards = cur.phrases.map(function (p) {
      return '<div class="card" style="gap:8px">' +
        '<div style="display:flex;gap:8px;align-items:flex-start;font-size:13.5px;line-height:1.45"><i class="ph ph-quotes" style="color:var(--color-accent);font-size:15px;flex:none;margin-top:2px"></i><em style="font-style:normal;color:var(--color-neutral-200)">“' + esc(p.say) + '”</em></div>' +
        '<div class="text-muted" style="font-size:12.5px;padding-left:23px">→ ' + esc(p.get) + '</div>' +
        '<div class="card-meta" style="padding-left:23px"><i class="ph ph-sparkle"></i> ' + esc(p.skill) + '</div></div>';
    }).join('');

    var skillRows = cur.skills.map(function (sk) {
      return '<tr><td style="font-family:ui-monospace,monospace;font-size:12.5px;color:var(--color-accent-300);white-space:nowrap">' + esc(sk.name) + '</td><td class="text-muted" style="font-size:13px">' + esc(sk.desc) + '</td></tr>';
    }).join('');

    // Step 1 body
    var step1;
    if (effGuided) {
      var toolRows = toolsFor(state.editor, state.os).map(function (tool) {
        return '<div style="display:grid;grid-template-columns:26px 140px 1fr auto;gap:12px;align-items:start;padding:11px 0;background:linear-gradient(to right, transparent, var(--color-divider) 48px, var(--color-divider) calc(100% - 48px), transparent) no-repeat bottom / 100% 1px">' +
          '<span style="width:22px;height:22px;border-radius:6px;background:var(--color-accent-900);color:var(--color-accent-300);display:inline-flex;align-items:center;justify-content:center;font-size:11px">' + tool.n + '</span>' +
          '<strong style="font-size:13.5px;font-weight:500;padding-top:2px">' + esc(tool.name) + '</strong>' +
          '<div style="min-width:0"><span class="text-muted" style="font-size:12.5px">' + esc(tool.hint) + ' — check: <code style="font-family:ui-monospace,monospace;font-size:12px;color:var(--color-accent-300)">' + esc(tool.check) + '</code></span>' +
          '<details style="margin-top:3px"><summary style="cursor:pointer;font-size:12px;color:var(--color-accent);list-style:none;display:inline-flex;align-items:center;gap:4px"><i class="ph ph-question"></i> Why do I need this?</summary>' +
          '<p class="text-muted" style="font-size:12.5px;margin:5px 0 0;max-width:480px">' + esc(tool.why) + '</p></details></div>' +
          '<a class="btn btn-ghost" href="' + esc(tool.url) + '" target="_blank" rel="noopener" style="font-size:12.5px">Download <i class="ph ph-arrow-square-out"></i></a></div>';
      }).join('');
      var terminalHint = isWin ? 'press Win+R, type cmd, press Enter' : 'press Cmd+Space, type Terminal, press Enter';
      step1 = '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">' +
        '<span class="text-muted" style="font-size:12.5px">Your computer:</span>' +
        '<div style="display:inline-flex;border:1px solid var(--color-divider);border-radius:8px;overflow:hidden" role="group" aria-label="Operating system">' +
        segBtn('set-os', 'win', isWin, '<i class="ph ph-windows-logo"></i> Windows') +
        segBtn('set-os', 'mac', !isWin, '<i class="ph ph-apple-logo"></i> macOS') + '</div></div>' +
        '<p class="text-muted" style="font-size:13.5px;margin:0">Four small installs, top to bottom. After each one, open a terminal (<strong>' + terminalHint + '</strong>) and paste the check command — if it answers with a version number, that tool is ready. Nothing here touches any project.</p>' +
        '<div style="display:flex;flex-direction:column">' + toolRows + '</div>';
    } else {
      var quickCheck = 'git --version && python3 --version && node --version';
      step1 = '<p class="text-muted" style="font-size:13.5px;margin:0">' + editorName + ', plus <code style="font-family:ui-monospace,monospace">git</code>, <code style="font-family:ui-monospace,monospace">python3</code> (enforcement hooks) and <code style="font-family:ui-monospace,monospace">node</code> (sdlc-preflight) on PATH. Optional: <code style="font-family:ui-monospace,monospace">gh</code> for GitHub ticket/MR adapters.</p>' +
        cmdBox(quickCheck, 'Copy');
    }

    // Step 2 body
    var step2;
    if (isCursor) {
      function mockFig(header, inner, caption) {
        return '<figure><div style="border:1px solid var(--color-divider);border-radius:8px;overflow:hidden;background:var(--color-bg)">' +
          '<div style="padding:7px 10px;background:var(--color-neutral-900);font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:var(--color-neutral-500)">' + header + '</div>' +
          '<div style="padding:12px;display:flex;flex-direction:column;gap:7px">' + inner + '</div></div>' +
          '<figcaption>' + caption + '</figcaption></figure>';
      }
      var skel = function (w) { return '<div style="height:7px;width:' + w + ';border-radius:4px;background:var(--color-neutral-800)"></div>'; };
      var installRow = function (name) { return '<div style="display:flex;justify-content:space-between;align-items:center;border:1px solid var(--color-divider);border-radius:6px;padding:5px 8px;font-size:10px"><span>' + name + '</span><span style="color:var(--color-accent)">Install</span></div>'; };
      step2 = '<p class="text-muted" style="font-size:13.5px;margin:0">agentic-os is a <strong>custom marketplace</strong> — you will not find it by searching Browse Marketplace → All. Add the marketplace once, then install from the <strong>User</strong> tab.</p>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin:6px 0 2px">' +
        mockFig('Customize · Plugins', skel('60%') + skel('45%') + '<div style="margin-top:4px;align-self:flex-start;border:1px solid var(--color-accent);color:var(--color-accent);border-radius:6px;padding:4px 9px;font-size:10.5px">+ Add marketplace</div>', '<strong>A.</strong> Customize → Plugins → <strong>Add marketplace</strong>') +
        mockFig('Add marketplace', '<div style="border:1px solid var(--color-accent);border-radius:6px;padding:5px 8px;font-family:ui-monospace,monospace;font-size:9.5px;color:var(--color-accent-300);overflow:hidden;white-space:nowrap;text-overflow:ellipsis">…/kinnister/agentic-os.git</div>' + skel('40%'), '<strong>B.</strong> Paste the Git URL — must end in <code style="font-family:ui-monospace,monospace">.git</code>') +
        mockFig('<span style="color:var(--color-accent-300)">User</span> · All', installRow('agentic-os') + installRow('Agentic SDLC'), '<strong>C.</strong> <strong>User</strong> tab — install both plugins') +
        mockFig('Browse · All', '<div style="border:1px solid var(--color-divider);border-radius:6px;padding:5px 8px;font-size:10px;color:var(--color-neutral-400)">🔍 superpowers</div>' +
          '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;border:1px solid var(--color-divider);border-radius:6px;padding:5px 8px;font-size:10px"><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Superpowers <span style="color:var(--color-neutral-500)">≥ 6.1.0</span></span><span style="color:var(--color-accent);flex:none">Install</span></div>', '<strong>D.</strong> Superpowers from Browse → <strong>All</strong> (public)') +
        '</div>' +
        cmdBox('https://github.com/kinnister/agentic-os.git', 'Copy URL') +
        '<p class="text-muted" style="font-size:13px;margin:0"><strong>E.</strong> Reload: <kbd style="border:1px solid var(--color-divider);border-radius:4px;padding:1px 5px;font-size:11px">Cmd/Ctrl+Shift+P</kbd> → “Developer: Reload Window”. All three plugins should show as cards (often tagged <em>Imported</em>). The flat “Rules, Skills, Subagents” list is <em>not</em> the install view.</p>';
    } else {
      var slash = function (cmd) {
        return '<div style="display:flex;align-items:center;gap:10px"><code style="flex:1;font-family:ui-monospace,monospace;font-size:12.5px;color:var(--color-neutral-200)">' + esc(cmd) + '</code>' + copyBtn(cmd) + '</div>';
      };
      step2 = '<p class="text-muted" style="font-size:13.5px;margin:0">Three slash commands in any Claude Code session, plus Superpowers:</p>' +
        '<div style="background:var(--color-neutral-900);border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:6px">' +
        slash('/plugin marketplace add kinnister/agentic-os') +
        slash('/plugin install agentic-os@agentic-os') +
        slash('/plugin install agentic-sdlc@agentic-os') + '</div>' +
        '<p class="text-muted" style="font-size:13px;margin:0">Superpowers ≥ 6.1.0 (required dependency):</p>' +
        '<div style="background:var(--color-neutral-900);border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:6px">' +
        slash('/plugin marketplace add anthropics/claude-plugins-official') +
        slash('/plugin install superpowers@claude-plugins-official') + '</div>' +
        '<p class="text-muted" style="font-size:13px;margin:0"><i class="ph ph-arrow-clockwise" style="color:var(--color-accent)"></i> <strong>Restart the session</strong> — Claude Code activates plugins at session start.</p>';
    }

    // Step 3 body
    var phaseRows = phasesFor(cur).map(function (phase) {
      return '<div style="display:grid;grid-template-columns:30px 130px 1fr;gap:12px;align-items:start;padding:9px 0;' + RULE_ROW + '">' +
        '<span style="width:26px;height:26px;border-radius:7px;border:1px solid var(--color-accent-700);color:var(--color-accent-300);display:inline-flex;align-items:center;justify-content:center"><i class="ph ' + phase.icon + '" style="font-size:14px"></i></span>' +
        '<strong style="font-size:13px;font-weight:500;padding-top:4px">' + esc(phase.name) + '</strong>' +
        '<span class="text-muted" style="font-size:12.5px;min-width:0;overflow-wrap:anywhere;padding-top:4px">' + esc(phase.desc) + '</span></div>';
    }).join('');
    var guidedSteps = effGuided
      ? '<ol class="text-muted" style="font-size:13.5px;margin:0;padding-left:20px;display:flex;flex-direction:column;gap:5px">' +
        '<li>' + (isCursor ? 'In Cursor: File → Open Folder → select your team repository' : 'Open a terminal, cd into your team repository folder, then run claude') + '</li>' +
        '<li>Open the <strong>' + chatPanelName + '</strong>, type the setup command below, press Enter, wait ~30 s</li>' +
        '<li>Type the verify command — expect <code style="font-family:ui-monospace,monospace;color:var(--color-accent-300)">passed: true</code></li></ol>'
      : '';
    var sdlcNote = cur.sdlc
      ? '<p class="text-muted" style="font-size:12.5px;margin:0">Before pipeline skills, also run <strong>sdlc-preflight</strong> (checks superpowers, node, git → <code style="font-family:ui-monospace,monospace;word-break:break-all">.agentic/agentic-sdlc/doctor.json</code>).</p>'
      : '';
    function successSign(icon, html) {
      return '<div style="display:flex;gap:9px;align-items:flex-start;font-size:12.5px;min-width:0;overflow-wrap:anywhere" class="text-muted"><i class="ph ' + icon + '" style="color:var(--color-accent);font-size:15px;flex:none;margin-top:1px"></i><span style="min-width:0">' + html + '</span></div>';
    }

    var completion = allDone
      ? '<section class="card" style="padding:20px;gap:8px;margin-bottom:14px;border:1px solid var(--color-accent);flex-direction:row;align-items:flex-start">' +
        '<i class="ph ph-confetti" style="color:var(--color-accent);font-size:22px;flex:none;margin-top:2px"></i>' +
        '<div><div class="card-title" style="margin-bottom:4px">You’re set — try your first prompt</div>' +
        '<p style="margin:0;font-size:13.5px;opacity:0.9">Open the ' + chatPanelName + ' in your team project and say: <em style="font-style:normal;color:var(--color-accent-300)">“' + esc(cur.phrases[0].say) + '”</em></p></div></section>'
      : '';

    var troubleRows = troublesFor(state.editor).map(function (t) {
      return '<tr><td style="font-size:13px">' + esc(t.sym) + '</td><td class="text-muted" style="font-size:13px">' + esc(t.fix) + '</td></tr>';
    }).join('');

    var guidedExtras = effGuided
      ? '<section class="card elev-sm" style="padding:20px;gap:10px;margin-bottom:14px">' +
        '<div class="card-kicker">Words you’ll meet</div>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px 20px">' +
        '<div><strong style="font-size:13px;font-weight:500">Preset</strong><p class="text-muted" style="font-size:12.5px;margin:3px 0 0">The role bundle /agentic-init installs — yours is ' + esc(d.presetLabel) + '.</p></div>' +
        '<div><strong style="font-size:13px;font-weight:500">Skill</strong><p class="text-muted" style="font-size:12.5px;margin:3px 0 0">A repeatable workflow the assistant runs the same way every time.</p></div>' +
        '<div><strong style="font-size:13px;font-weight:500">HITL</strong><p class="text-muted" style="font-size:12.5px;margin:3px 0 0">Human-in-the-loop — you approve before anything changes tickets or the repo.</p></div>' +
        '<div><strong style="font-size:13px;font-weight:500">Gate</strong><p class="text-muted" style="font-size:12.5px;margin:3px 0 0">A checkpoint where work pauses for a decision — yours or a governed agent’s.</p></div>' +
        '<div><strong style="font-size:13px;font-weight:500">Marketplace</strong><p class="text-muted" style="font-size:12.5px;margin:3px 0 0">Where plugins install from. agentic-os is a custom one you add by URL.</p></div>' +
        '<div><strong style="font-size:13px;font-weight:500">MCP</strong><p class="text-muted" style="font-size:12.5px;margin:3px 0 0">Optional connector to approved tools (e.g. your ticket system). Pasting text works without it — see the <a href="#mcp">MCP guide</a>.</p></div>' +
        '</div></section>' +
        '<div class="card" style="flex-direction:row;gap:12px;align-items:flex-start;border:1px dashed var(--color-divider);background:transparent">' +
        '<i class="ph ph-buildings" style="color:var(--color-accent);font-size:16px;margin-top:1px"></i>' +
        '<p class="text-muted" style="margin:0;font-size:12.5px"><strong style="color:var(--color-text);font-weight:500">Corporate network?</strong> If the marketplace won’t add, IT may block GitHub or custom marketplaces. Share this with them: access to <code style="font-family:ui-monospace,monospace">github.com/kinnister/agentic-os</code>, the plugin-marketplace feature enabled, and outbound HTTPS for editor updates.</p></div>'
      : '';

    return '<main style="max-width:880px;margin:0 auto;padding:28px 22px 70px">' +
      '<a href="#" class="btn btn-ghost" style="margin-bottom:22px"><i class="ph ph-arrow-left"></i> All roles</a>' +

      '<header style="display:flex;gap:18px;align-items:flex-start">' +
      '<span style="width:52px;height:52px;flex:none;border-radius:13px;background:var(--color-accent-900);color:var(--color-accent-300);display:inline-flex;align-items:center;justify-content:center"><i class="ph ' + cur.icon + '" style="font-size:27px"></i></span>' +
      '<div><h1 style="font-size:34px;margin-bottom:8px">Agentic OS for ' + esc(cur.longLabel) + '</h1>' +
      '<p class="text-muted" style="font-size:15px;max-width:560px;margin-bottom:12px">' + esc(cur.tagline) + '</p>' +
      '<div style="display:flex;flex-wrap:wrap;gap:8px">' +
      '<span class="tag ' + d.levelTagClass + '">' + esc(d.levelLabel) + '</span>' +
      '<span class="tag tag-neutral" title="How much agents may do before a human must approve">' + esc(d.hitlLabel) + '</span>' +
      '<span class="tag tag-neutral" title="How work is routed to agents">' + esc(d.orchLabel) + '</span>' +
      '<span class="tag tag-outline">' + esc(cur.time) + '</span></div></div></header>' +

      '<div class="card" style="flex-direction:row;gap:12px;align-items:flex-start;margin-top:24px;border-left:2px solid var(--color-accent)">' +
      '<i class="ph ph-shield-check" style="color:var(--color-accent);font-size:17px;margin-top:1px"></i>' +
      '<p style="margin:0;font-size:13.5px;opacity:0.9">' + esc(cur.note) + '</p></div>' +

      '<hr class="hr" style="margin:32px 0 26px">' +
      '<h3 style="margin-bottom:4px">Say it in chat</h3>' +
      '<p class="text-muted" style="font-size:13.5px;margin-bottom:16px">After setup, plain English is enough for daily work — no slash commands needed unless shown.</p>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px">' + phraseCards + '</div>' +

      '<details style="margin-top:14px"><summary style="cursor:pointer;font-size:13px;color:var(--color-accent)">Installed skills (' + cur.skills.length + ')</summary>' +
      '<table class="table" style="margin-top:10px"><thead><tr><th>Skill</th><th>Purpose</th></tr></thead><tbody>' + skillRows + '</tbody></table></details>' +

      '<hr class="hr" style="margin:32px 0 26px">' +
      '<div style="background:linear-gradient(135deg, var(--color-section), var(--color-section-glow));border-radius:var(--radius-lg);padding:22px 24px;margin-bottom:20px">' +
      '<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px;margin-bottom:6px">' +
      '<h3 style="margin:0">Install</h3>' +
      '<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">' +
      '<div style="display:inline-flex;border:1px solid var(--color-divider);border-radius:8px;overflow:hidden" role="group" aria-label="Editor">' +
      segBtn('set-editor', 'cursor', isCursor, '<i class="ph ph-cursor-click"></i> Cursor') +
      segBtn('set-editor', 'claude', !isCursor, '<i class="ph ph-terminal-window"></i> Claude Code') + '</div>' +
      '<div style="display:inline-flex;border:1px solid var(--color-divider);border-radius:8px;overflow:hidden" role="group" aria-label="Level of detail">' +
      segBtn('set-detail', 'quick', !effGuided, '<i class="ph ph-lightning"></i> Quick', 'Terse steps for people who live in a terminal') +
      segBtn('set-detail', 'guided', effGuided, '<i class="ph ph-steps"></i> Walk me through', 'Every click spelled out — no terminal experience assumed') + '</div>' +
      '</div></div>' +
      '<p style="font-size:12.5px;margin:0 0 12px;color:color-mix(in srgb, var(--color-text) 70%, transparent)">Pick your editor and how much detail you want — your choice is remembered.</p>' +
      '<div style="display:flex;align-items:center;gap:12px">' +
      '<div role="progressbar" aria-valuemin="0" aria-valuemax="' + checklist.length + '" aria-valuenow="' + doneCount + '" aria-label="Install progress" style="flex:1;height:3px;border-radius:2px;background:var(--color-section-ghost);overflow:hidden"><div style="height:100%;width:' + pct + '%;background:var(--color-accent);border-radius:2px;transition:width 0.25s ease"></div></div>' +
      '<span style="font-size:12px;flex:none;color:color-mix(in srgb, var(--color-text) 70%, transparent)">' + doneCount + ' of ' + checklist.length + ' done — saves in this browser</span></div></div>' +

      '<section class="card elev-sm" style="padding:20px;gap:12px;margin-bottom:14px">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px"><span class="card-kicker">Step 1 · Once per laptop</span><span class="text-muted" style="font-size:11.5px">' + stepStatus(checklist, 1) + '</span></div>' +
      '<h4 style="margin:0">Machine tools</h4>' + step1 +
      checkSection(cur.id, checklist.filter(function (i) { return i.step === 1; })) + '</section>' +

      '<section class="card elev-sm" style="padding:20px;gap:12px;margin-bottom:14px">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px"><span class="card-kicker">Step 2 · Once per editor</span><span class="text-muted" style="font-size:11.5px">' + stepStatus(checklist, 2) + '</span></div>' +
      '<h4 style="margin:0">Add the plugins</h4>' + step2 +
      checkSection(cur.id, checklist.filter(function (i) { return i.step === 2; })) + '</section>' +

      '<section class="card elev-sm" style="padding:20px;gap:12px;margin-bottom:14px">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px"><span class="card-kicker">Step 3 · ~2 min per repo</span><span class="text-muted" style="font-size:11.5px">' + stepStatus(checklist, 3) + '</span></div>' +
      '<h4 style="margin:0">Equip your project</h4>' +
      '<div class="card" style="flex-direction:row;gap:10px;align-items:flex-start;background:var(--color-accent-900);padding:10px 14px">' +
      '<i class="ph ph-warning" style="color:var(--color-accent-200);font-size:15px;margin-top:1px"></i>' +
      '<p style="margin:0;font-size:12.5px;color:var(--color-accent-100)">Open <strong>your team project</strong> — never the agentic-os marketplace clone. It must be a git repository (<code style="font-family:ui-monospace,monospace">git status</code> works; if not, ask your dev lead to clone it for you).</p></div>' +
      guidedSteps +
      '<p class="text-muted" style="font-size:12.5px;margin:0">Setup — installs the <strong>' + esc(d.presetLabel) + '</strong> preset' + d.presetPlural + ':</p>' +
      cmdBox(d.initCmd, 'Copy') +
      '<p class="text-muted" style="font-size:12.5px;margin:0">Verify:</p>' +
      cmdBox('/agentic-doctor', 'Copy') +
      '<details style="border:1px solid var(--color-divider);border-radius:8px;padding:12px 14px">' +
      '<summary style="cursor:pointer;font-size:13px;color:var(--color-accent);list-style:none;display:inline-flex;align-items:center;gap:6px"><i class="ph ph-play-circle"></i> What actually happens when you run it</summary>' +
      '<div style="display:flex;flex-direction:column;gap:0;margin-top:12px">' + phaseRows + '</div></details>' +
      sdlcNote +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:4px">' +
      successSign('ph-check-circle', 'Doctor reports <code style="font-family:ui-monospace,monospace;word-break:break-all">passed: true</code> in <code style="font-family:ui-monospace,monospace;word-break:break-all">.agentic/agentic-os/doctor.json</code>') +
      successSign('ph-folder-simple-plus', 'A new <code style="font-family:ui-monospace,monospace">.agentic/</code> folder appears — guides, policies, install journal') +
      successSign('ph-git-diff', '<strong>Nothing is committed for you</strong> — <code style="font-family:ui-monospace,monospace">git status</code> shows the files; you review and commit') +
      successSign('ph-arrow-u-up-left', '<strong>Reversible</strong> — <code style="font-family:ui-monospace,monospace">/agentic-uninstall ' + esc(cur.id) + '</code> drops the role again, <code style="font-family:ui-monospace,monospace">--all</code> removes the layer, <code style="font-family:ui-monospace,monospace">--dry-run</code> previews either') +
      '</div>' +
      checkSection(cur.id, checklist.filter(function (i) { return i.step === 3; })) + '</section>' +

      completion +

      '<section class="card elev-sm" style="padding:20px;gap:12px;margin-bottom:14px">' +
      '<div class="card-kicker">Troubleshooting</div>' +
      '<h4 style="margin:0">Something went wrong?</h4>' +
      '<table class="table"><thead><tr><th style="width:44%">Symptom</th><th>Fix</th></tr></thead><tbody>' + troubleRows + '</tbody></table></section>' +

      guidedExtras +
      '</main>';
  }

  function renderMcp() {
    function capCard(icon, title, body) {
      return '<div class="card" style="gap:6px"><i class="ph ' + icon + '" style="color:var(--color-accent);font-size:18px"></i><div class="card-title" style="font-size:14.5px">' + title + '</div><p class="card-body">' + body + '</p></div>';
    }
    return '<main style="max-width:880px;margin:0 auto;padding:28px 22px 70px">' +
      '<a href="#" class="btn btn-ghost" style="margin-bottom:22px"><i class="ph ph-arrow-left"></i> All roles</a>' +
      '<header style="display:flex;gap:18px;align-items:flex-start">' +
      '<span style="width:52px;height:52px;flex:none;border-radius:13px;background:var(--color-accent-900);color:var(--color-accent-300);display:inline-flex;align-items:center;justify-content:center"><i class="ph ph-plugs-connected" style="font-size:27px"></i></span>' +
      '<div><h1 style="font-size:34px;margin-bottom:8px">The MCP path</h1>' +
      '<p class="text-muted" style="font-size:15px;max-width:580px;margin-bottom:12px">Not on Cursor or Claude Code? The same governance, SDLC and QE methodology is a published, <strong>read-only</strong> MCP server — usable from any MCP-capable assistant. It advises; the editor plugins do the installing.</p>' +
      '<div style="display:flex;flex-wrap:wrap;gap:8px">' +
      '<span class="tag tag-accent">Any MCP client</span>' +
      '<span class="tag tag-neutral">read-only</span>' +
      '<span class="tag tag-outline">no plugins needed</span></div></div></header>' +

      '<hr class="hr" style="margin:30px 0 24px">' +
      '<h4 style="margin-bottom:12px">What your assistant can do with it</h4>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px">' +
      capCard('ph-magnifying-glass', 'Search the docs', 'Governance, SDLC and QE methodology, queryable in place.') +
      capCard('ph-users-three', 'List role presets', 'All ten roles and the 28 QE blueprints, with what each installs.') +
      capCard('ph-list-checks', 'Plan an install', 'Turn a role into a concrete install plan for your setup.') +
      capCard('ph-stethoscope', 'Audit an install', 'Check an existing .agentic/ install against the methodology.') + '</div>' +

      '<section class="card elev-sm" style="padding:20px;gap:12px;margin-top:24px">' +
      '<div class="card-kicker">Connect</div>' +
      '<p class="text-muted" style="font-size:13px;margin:0">Claude Code (or the claude CLI):</p>' +
      cmdBox('claude mcp add agentic-os -- npx -y agentic-os-mcp', 'Copy') +
      '<p class="text-muted" style="font-size:13px;margin:0">Any other MCP client — register a stdio server with:</p>' +
      cmdBox('npx -y agentic-os-mcp', 'Copy') +
      '<table class="table" style="margin-top:6px"><thead><tr><th>Where config lives</th><th>File</th><th>Verify</th></tr></thead><tbody>' +
      '<tr><td style="font-size:13px">Cursor — project</td><td style="font-family:ui-monospace,monospace;font-size:12.5px;color:var(--color-accent-300)">.cursor/mcp.json</td><td style="font-family:ui-monospace,monospace;font-size:12.5px" class="text-muted">cursor-agent mcp list</td></tr>' +
      '<tr><td style="font-size:13px">Cursor — global</td><td style="font-family:ui-monospace,monospace;font-size:12.5px;color:var(--color-accent-300)">~/.cursor/mcp.json</td><td style="font-family:ui-monospace,monospace;font-size:12.5px" class="text-muted">cursor-agent mcp list-tools</td></tr>' +
      '<tr><td style="font-size:13px">Claude Code — project</td><td style="font-family:ui-monospace,monospace;font-size:12.5px;color:var(--color-accent-300)">.mcp.json</td><td style="font-family:ui-monospace,monospace;font-size:12.5px" class="text-muted">claude mcp list · /mcp</td></tr>' +
      '</tbody></table>' +
      '<p class="text-muted" style="font-size:12.5px;margin:0"><i class="ph ph-key" style="color:var(--color-accent)"></i> Keep secrets in OAuth or environment variables — never in committed JSON.</p></section>' +

      '<div class="card" style="flex-direction:row;gap:12px;align-items:flex-start;margin-top:14px;border-left:2px solid var(--color-accent)">' +
      '<i class="ph ph-info" style="color:var(--color-accent);font-size:16px;margin-top:1px"></i>' +
      '<p style="margin:0;font-size:13px;opacity:0.9">Different thing, same acronym: connecting <em>your own tools</em> (e.g. Azure DevOps) to the editor is also MCP, configured in the same files — ask your tech lead. Pasting ticket text into chat always works without it.</p></div>' +
      '</main>';
  }

  // ── render loop ──
  var root = document.getElementById('view');

  function render(animate) {
    var cur = ROLES.find(function (r) { return r.id === state.view; });
    // Re-renders triggered by toggles rebuild the DOM, which would collapse
    // any open <details> and drop focus — snapshot and restore both.
    var openStates = Array.prototype.map.call(root.querySelectorAll('details'), function (dt) { return dt.open; });
    var focused = document.activeElement;
    var focusSel = null;
    if (focused && root.contains(focused)) {
      if (focused.dataset.key) focusSel = 'input[data-key="' + focused.dataset.key + '"]';
      else if (focused.dataset.action) focusSel = '[data-action="' + focused.dataset.action + '"][data-val="' + focused.dataset.val + '"]';
    }

    var html;
    if (cur) html = renderRole(cur);
    else if (state.view === 'mcp') html = renderMcp();
    else html = renderHome();
    root.innerHTML = html;
    var main = root.firstElementChild;
    if (animate && main) main.classList.add('viewin');
    if (!animate) {
      Array.prototype.forEach.call(root.querySelectorAll('details'), function (dt, i) {
        if (openStates[i] !== undefined) dt.open = openStates[i];
      });
      if (focusSel) {
        var el = root.querySelector(focusSel);
        if (el) el.focus();
      }
    }
  }

  window.addEventListener('hashchange', function () {
    state.view = location.hash.replace('#', '') || 'home';
    render(true);
    window.scrollTo(0, 0);
  });

  root.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-cmd], [data-action]');
    if (!btn || !root.contains(btn)) return;
    if (btn.dataset.cmd) {
      navigator.clipboard.writeText(btn.dataset.cmd).then(function () {
        var prev = btn.innerHTML;
        btn.innerHTML = '<i class="ph ph-check"></i> Copied';
        setTimeout(function () { btn.innerHTML = prev; }, 1400);
      });
      return;
    }
    var val = btn.dataset.val;
    if (btn.dataset.action === 'set-editor') {
      state.editor = val;
      localStorage.setItem(LS.editor, val);
    } else if (btn.dataset.action === 'set-os') {
      state.os = val;
      localStorage.setItem(LS.os, val);
    } else if (btn.dataset.action === 'set-detail') {
      var cur = ROLES.find(function (r) { return r.id === state.view; });
      if (!cur) return;
      state.detailOv[cur.id] = val === 'guided';
      localStorage.setItem(LS.detail, JSON.stringify(state.detailOv));
    }
    render(false);
  });

  root.addEventListener('change', function (e) {
    var box = e.target.closest('input[data-key]');
    if (!box) return;
    var cur = ROLES.find(function (r) { return r.id === state.view; });
    if (!cur) return;
    state.checks[cur.id + ':' + box.dataset.key] = box.checked;
    localStorage.setItem(LS.checks, JSON.stringify(state.checks));
    render(false);
  });

  render(true);
})();
