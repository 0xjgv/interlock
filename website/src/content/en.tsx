import {
    SectionHeading,
    P,
    Code,
    CodeBlock,
    List,
    Li,
    type EditorialSection,
} from '../components/markdown';
import type { FlatTocItem, TocNodeType } from '../components/toc-tree';

function tocItem(
    href: string,
    label: string,
    opts: { level?: 0 | 1 | 2 | 3; parent?: string; prefix?: string; type?: TocNodeType } = {},
): FlatTocItem {
    return {
        href,
        label,
        type: opts.type ?? (`h${Math.min(6, (opts.level ?? 0) + 2)}` as TocNodeType),
        visualLevel: (opts.level ?? 0) as FlatTocItem['visualLevel'],
        prefix: opts.prefix ?? '',
        parentHref: opts.parent ?? null,
        pageHref: '/',
    };
}

/* =========================================================================
   Config-key row type (section #config).
   Each row cites CLAUDE.md:34-61 for the exact key / default / note source.
   ========================================================================= */
type ConfigRow = {
    key: string;
    type: string;
    default: string;
    note: string;
};

const CONFIG_ROWS: ConfigRow[] = [
    { key: 'preset', type: '"baseline" | "strict" | "legacy"', default: 'unset', note: 'named adoption posture; explicit values still win' },
    // Paths / runners — CLAUDE.md:36-40
    { key: 'src_dir', type: 'string', default: 'auto-detect', note: 'src/<pkg>, top-level pkg, or [tool.uv.build-backend]' },
    { key: 'test_dir', type: 'string', default: 'auto-detect', note: 'first existing of tests/, test/, src/tests/' },
    { key: 'test_runner', type: '"pytest" | "unittest"', default: 'auto', note: 'from pytest config / deps / import' },
    { key: 'test_invoker', type: '"python" | "uv"', default: 'auto', note: '"uv" when uv.lock present' },
    { key: 'pytest_args', type: 'string[]', default: '[]', note: 'extra args appended to pytest commands' },
    // Thresholds — CLAUDE.md:43-50
    { key: 'coverage_min', type: 'int', default: '80', note: '`coverage` fail-under' },
    { key: 'crap_max', type: 'float', default: '30.0', note: '`crap` CRAP ceiling' },
    { key: 'complexity_max_ccn', type: 'int', default: '15', note: 'lizard cyclomatic-complexity cap' },
    { key: 'complexity_max_args', type: 'int', default: '7', note: 'lizard argument-count cap' },
    { key: 'complexity_max_loc', type: 'int', default: '100', note: 'lizard LOC cap' },
    { key: 'mutation_min_coverage', type: 'float', default: '70.0', note: '`mutation` skips when suite coverage is lower' },
    { key: 'mutation_max_runtime', type: 'int', default: '600', note: '`mutation` seconds before SIGTERM' },
    { key: 'mutation_min_score', type: 'float', default: '80.0', note: 'kill ratio (%) enforced when blocking' },
    // Gate enforcement — CLAUDE.md:53-55
    { key: 'enforce_crap', type: 'bool', default: 'true', note: 'CRAP exits 1 on offenders (set false to stay advisory)' },
    { key: 'run_mutation_in_ci', type: 'bool', default: 'false', note: 'include mutation in `harness ci`' },
    { key: 'enforce_mutation', type: 'bool', default: 'false', note: 'mutation exits 1 when score < mutation_min_score' },
    { key: 'mutation_ci_mode', type: '"off" | "incremental" | "full"', default: '"off"', note: 'future mutation scheduling posture' },
    // Acceptance — CLAUDE.md:58-60
    { key: 'acceptance_runner', type: '"pytest-bdd" | "behave" | "off"', default: 'auto', note: 'explicit override wins' },
    { key: 'features_dir', type: 'string', default: 'auto-detect', note: 'tests/features/, features/, <test_dir>/features/' },
    { key: 'run_acceptance_in_check', type: 'bool', default: 'false', note: 'true → run scenarios inside `harness check`' },
];

const TABLE_CELL: React.CSSProperties = {
    padding: '4px 12px 4px 0',
    borderBottom: '1px solid var(--page-border)',
};
const TABLE_TH: React.CSSProperties = { ...TABLE_CELL, textAlign: 'left', fontFamily: 'var(--font-primary)' };
const TABLE_TD_CODE: React.CSSProperties = { ...TABLE_CELL, fontFamily: 'var(--font-code)', whiteSpace: 'nowrap' };
const TABLE_TD_PROSE: React.CSSProperties = { ...TABLE_CELL, fontFamily: 'var(--font-primary)' };

/* Render inline backtick spans as <code>. Strips pairs of ` and wraps the
   enclosed token in <code>; unwrapped text passes through. */
function RenderNote({ text }: { text: string }) {
    const parts = text.split(/(`[^`]+`)/g);
    return (
        <>
            {parts.map((p, i) =>
                p.startsWith('`') && p.endsWith('`') ? (
                    <code key={i} style={{ fontFamily: 'var(--font-code)' }}>
                        {p.slice(1, -1)}
                    </code>
                ) : (
                    <span key={i}>{p}</span>
                ),
            )}
        </>
    );
}

function ConfigTable({ rows }: { rows: ConfigRow[] }) {
    return (
        <div style={{ width: '100%', overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 'var(--type-table-size)' }}>
                <thead>
                    <tr>
                        <th style={TABLE_TH}>Key</th>
                        <th style={TABLE_TH}>Type</th>
                        <th style={TABLE_TH}>Default</th>
                        <th style={TABLE_TH}>Note</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row) => (
                        <tr key={row.key}>
                            <td style={TABLE_TD_CODE}>{row.key}</td>
                            <td style={TABLE_TD_CODE}>{row.type}</td>
                            <td style={TABLE_TD_CODE}>{row.default}</td>
                            <td style={TABLE_TD_PROSE}><RenderNote text={row.note} /></td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

export const pageContent = {
    meta: {
        // pyproject.toml:4 — "Zero-config Python quality harness … all behind `harness <task>`."
        title: 'pyharness — Zero-config Python quality harness.',
        description:
            'Install pyharness, run `harness doctor`, use `harness check` locally, and wire `harness ci` in CI.',
    },

    toc: [
        tocItem('#overview', 'Overview'),
        tocItem('#quick-start', 'Quick start'),
        tocItem('#ci', 'GitHub CI'),
        tocItem('#stages', 'Stages'),
        tocItem('#tasks', 'Tasks'),
        tocItem('#config', 'Configuration'),
        tocItem('#hooks', 'Hooks'),
    ] as FlatTocItem[],

    hero: (
        <div style={{ padding: '20px 0 8px' }}>
            <p
                style={{
                    fontFamily: 'var(--font-secondary)',
                    fontStyle: 'italic',
                    fontSize: '19px',
                    fontWeight: 400,
                    lineHeight: 1.55,
                    color: 'var(--text-primary)',
                    margin: 0,
                }}
            >
                Install pyharness, run <code>harness doctor</code>, use{' '}
                <code>harness check</code> locally, and wire <code>harness ci</code> in CI.
            </p>
        </div>
    ),

    sections: [
        /* ── Overview ── */
        {
            content: (
                <>
                    <SectionHeading id="overview" level={1}>
                        Overview
                    </SectionHeading>
                    <P>
                        pyharness packages the adoption loop for Python repositories: diagnose
                        readiness, run local checks, and wire CI without copying tool-specific
                        scripts into every project.
                    </P>
                    <P>
                        Source and test directories, test runner, invoker, and features directory
                        auto-detect from the nearest <Code>pyproject.toml</Code>. Choose an
                        adoption preset when useful, then override individual keys only when you
                        need to.
                    </P>
                </>
            ),
            aside: (
                <P>
                    {/* README.md:5 — bundled tools, no extra pip install dance. */}
                    Every tool (ruff, basedpyright, coverage, pytest, pytest-bdd, lizard, mutmut,
                    pip-audit, deptry, import-linter) ships with the CLI. No extra{' '}
                    <Code>pip install</Code> dance.
                </P>
            ),
        },

        /* ── Quick start ── */
        {
            content: (
                <>
                    <SectionHeading id="quick-start" level={1}>
                        Quick start
                    </SectionHeading>
                    <CodeBlock lang="bash">{`# 1. Install (pipx or uv tool)
pipx install pyharness
# or:
uv tool install pyharness`}</CodeBlock>

                    <CodeBlock lang="bash">{`# 2. Diagnose readiness
cd your-python-project
harness doctor`}</CodeBlock>

                    <CodeBlock lang="bash">{`# 3. Run the local edit loop
harness check`}</CodeBlock>

                    <CodeBlock lang="bash">{`# 4. Wire CI
harness ci`}</CodeBlock>
                </>
            ),
            aside: (
                <P>
                    <Code>harness doctor</Code> stays static and cheap: it reports readiness,
                    blockers, warnings, detected config, and next steps without running expensive
                    gates.
                </P>
            ),
        },

        /* ── CI ── */
        {
            content: (
                <>
                    <SectionHeading id="ci" level={1}>
                        GitHub CI
                    </SectionHeading>
                    <P>
                        The reusable action installs pyharness and delegates the quality pipeline
                        to <Code>harness ci</Code>. It writes a concise GitHub job summary when the
                        summary file is available.
                    </P>
                    <CodeBlock lang="yaml">{`name: pyharness

on:
  pull_request:
  push:
    branches: [main]

jobs:
  pyharness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: 0xjgv/pyharness@v1`}</CodeBlock>
                </>
            ),
            aside: (
                <P>
                    The action does not duplicate lint, typecheck, coverage, CRAP, dependency,
                    architecture, acceptance, or mutation logic. The CLI remains the source of
                    truth.
                </P>
            ),
        },

        /* ── Stages ── */
        {
            content: (
                <>
                    <SectionHeading id="stages" level={1}>
                        Stages
                    </SectionHeading>
                    <P>
                        High-level entry points. Use <Code>doctor</Code>, <Code>check</Code>, and{' '}
                        <Code>ci</Code> for adoption; reach for individual tasks when debugging.
                    </P>
                    {/* README.md:23-29 + CLAUDE.md:9-17 — five stages, when they run, what they run. */}
                    <CodeBlock lang="diagram" showLineNumbers={false}>{` Stage              When                       What runs
 ────────────────────────────────────────────────────────────────────────────────
 harness check      After edits (dev loop)     fix → format → typecheck → test
                                               (+ acceptance if opted in)
 harness pre-commit Git pre-commit hook        staged-file fix/format, re-stage,
                                               typecheck, test (if src_dir touched)
 harness ci         On every PR                lint, format-check, typecheck, deps,
                                               complexity, coverage, arch,
                                               acceptance → CRAP (blocking)
 harness nightly    Cron / scheduled           coverage → mutation
                                               (always blocking on mutation_min_score)
 harness post-edit  Stable post-edit hook      ruff fix + format on touched files
                                               (silent no-op otherwise)`}</CodeBlock>
                    <P>
                        {/* README.md:33 — nightly overrides enforce_mutation by design. */}
                        <Code>harness nightly</Code> overrides <Code>enforce_mutation</Code> — by
                        design it always fails the run when the score drops. That's the point of
                        nightly.
                    </P>
                </>
            ),
            aside: (
                <P>
                    {/* README.md:31 — footnote: opt in via run_acceptance_in_check; arch/acceptance skip silently. */}
                    Acceptance opts into <Code>harness check</Code> via{' '}
                    <Code>run_acceptance_in_check = true</Code>. Arch and acceptance skip silently
                    if not configured / no features dir.
                </P>
            ),
        },

        /* ── Tasks ── */
        {
            content: (
                <>
                    <SectionHeading id="tasks" level={1}>
                        Tasks
                    </SectionHeading>
                    <P>
                        {/* README.md:37 + harness/cli.py:80-126 — tasks read config + CLI flags, shared runner. */}
                        Individual commands. Each reads config + CLI flags. Most call through a
                        shared runner so output is consistent.
                    </P>

                    {/* harness/cli.py:84-89 — correctness tasks. README.md:40-44 — mirrors. */}
                    <SectionHeading id="tasks-correctness" level={2}>
                        Correctness
                    </SectionHeading>
                    <List>
                        <Li>
                            {/* cli.py:84-85 + README.md:40 — ruff lint-fix + format (mutate files). */}
                            <Code>fix</Code> / <Code>format</Code> — ruff lint-fix and format
                            (mutates files)
                        </Li>
                        <Li>
                            {/* README.md:41 — read-only equivalents for CI. cli.py:86. */}
                            <Code>lint</Code> / <Code>format-check</Code> — read-only equivalents
                            for CI
                        </Li>
                        <Li>
                            {/* cli.py:87 + README.md:42 — basedpyright. */}
                            <Code>typecheck</Code> — basedpyright
                        </Li>
                        <Li>
                            {/* cli.py:88 + README.md:43 — auto-detect pytest vs unittest. */}
                            <Code>test</Code> — pytest or unittest (auto)
                        </Li>
                    </List>
                    <CodeBlock lang="bash">{`harness fix
harness format
harness typecheck
harness test`}</CodeBlock>

                    {/* harness/cli.py:89-95 — hygiene tasks. README.md:46-49 — mirrors. */}
                    <SectionHeading id="tasks-hygiene" level={2}>
                        Hygiene
                    </SectionHeading>
                    <List>
                        <Li>
                            {/* cli.py:89 + README.md:47 — pip-audit CVE scan. */}
                            <Code>audit</Code> — pip-audit CVE scan
                        </Li>
                        <Li>
                            {/* cli.py:90 + README.md:48 — deptry unused/missing/transitive. */}
                            <Code>deps</Code> — deptry: unused, missing, transitive imports
                        </Li>
                        <Li>
                            {/* cli.py:91 + README.md:49 — import-linter default src ↛ tests. */}
                            <Code>arch</Code> — import-linter contracts (default:{' '}
                            <Code>src ↛ tests</Code>)
                        </Li>
                        <Li>
                            {/* cli.py:92-95 + README.md:44 — Gherkin via pytest-bdd or behave. */}
                            <Code>acceptance</Code> — Gherkin via pytest-bdd (default) or behave
                        </Li>
                    </List>
                    <CodeBlock lang="bash">{`harness audit
harness deps
harness arch
harness acceptance`}</CodeBlock>

                    {/* harness/cli.py:100-105 — gate tasks. README.md:52-54 — mirrors. */}
                    <SectionHeading id="tasks-gates" level={2}>
                        Gates
                    </SectionHeading>
                    <List>
                        <Li>
                            {/* cli.py:100 + README.md:52 + CLAUDE.md:18 — coverage.py fail-under. */}
                            <Code>coverage --min=N</Code> — coverage.py with fail-under
                        </Li>
                        <Li>
                            {/* cli.py:101 + README.md:53 + CLAUDE.md:19 — CRAP blocking by default. */}
                            <Code>crap --max=N</Code> — complexity × coverage gate, blocking by
                            default
                        </Li>
                        <Li>
                            {/* cli.py:102-105 + README.md:54 + CLAUDE.md:20 — mutmut; advisory unless gated. */}
                            <Code>mutation --max-runtime=N</Code> — mutmut; advisory unless{' '}
                            <Code>enforce_mutation = true</Code> or <Code>--min-score=</Code>{' '}
                            passed
                        </Li>
                        <Li>
                            {/* CLAUDE.md:11 + pyproject.toml:98-101 — complexity is exposed via the CCN cap
                                (default 15), enforced inside `harness ci`. */}
                            <strong>complexity</strong> — lizard CCN / args / LOC caps (enforced
                            in <Code>harness ci</Code>)
                        </Li>
                    </List>
                    <CodeBlock lang="bash">{`harness coverage --min=80
harness crap --max=30
harness mutation --min-coverage=70 --max-runtime=600`}</CodeBlock>
                </>
            ),
            aside: (
                <P>
                    {/* README.md:56-60 — scaffolding + housekeeping tasks. cli.py:96-99 + 116-117. */}
                    Also: <Code>doctor</Code> (adoption diagnostic),{' '}
                    <Code>init-acceptance</Code> (scaffold tests/features),{' '}
                    <Code>setup-hooks</Code> (convenience hook installer), <Code>clean</Code>{' '}
                    (caches + mutation state), <Code>help</Code> (detected paths, preset, and
                    thresholds).
                </P>
            ),
        },

        /* ── Configuration ── */
        {
            content: (
                <>
                    <SectionHeading id="config" level={1}>
                        Configuration
                    </SectionHeading>
                    <P>
                        {/* CLAUDE.md:31 — walks up from CWD to nearest pyproject.toml; all keys optional. */}
                        <Code>harness</Code> walks up from CWD to the nearest{' '}
                        <Code>pyproject.toml</Code> and auto-detects everything below. All keys
                        under <Code>[tool.harness]</Code> are optional. Use{' '}
                        <Code>preset = &quot;baseline&quot;</Code>, <Code>&quot;strict&quot;</Code>, or{' '}
                        <Code>&quot;legacy&quot;</Code> to select an adoption posture.
                    </P>

                    {/* CLAUDE.md:34-61 — full 19-key config block. */}
                    <ConfigTable rows={CONFIG_ROWS} />
                </>
            ),
            aside: (
                <P>
                    {/* CLAUDE.md:67-72 — precedence cascade: CLI flag > [tool.harness] > user-global > bundled defaults. */}
                    Precedence: bundled defaults &lt; user-global preset &lt; user-global explicit
                    values &lt; project preset &lt; project explicit values &lt; CLI flags.
                </P>
            ),
        },

        /* ── Hooks ── */
        {
            content: (
                <>
                    <SectionHeading id="hooks" level={1}>
                        Hooks
                    </SectionHeading>
                    {/* README.md:151 + CLAUDE.md:21 — single command installs both. */}
                    <CodeBlock lang="bash">{`harness setup-hooks`}</CodeBlock>
                    <P>Installs two things:</P>
                    <List>
                        <Li>
                            {/* README.md:156 + harness/stages/setup_hooks.py:62-66 — writes .git/hooks/pre-commit
                                and chmod 0755; skip with --no-verify. */}
                            <Code>.git/hooks/pre-commit</Code> — runs the stable{' '}
                            <Code>harness pre-commit</Code> interface on staged files. Skip with{' '}
                            <Code>git commit --no-verify</Code>.
                        </Li>
                        <Li>
                            {/* README.md:157 + CLAUDE.md:22 + setup_hooks.py:68-78 — merges into existing
                                .claude/settings.json Stop hook, idempotent (_ensure_stop_hook dedupes). */}
                            <Code>.claude/settings.json</Code> Stop hook — runs the stable{' '}
                            <Code>harness post-edit</Code> interface after Claude Code sessions,
                            formatting any files the session touched. Merges into existing hooks;
                            idempotent.
                        </Li>
                    </List>
                    <P>
                        {/* README.md:159 + setup_hooks.py:60 — uses sys.executable (shlex.quote) so hooks
                            survive venv changes. */}
                        Both reference the Python that installed pyharness, so they survive venv
                        changes.
                    </P>
                    <div style={{ paddingBottom: '80px' }} />
                </>
            ),
            aside: (
                <P>
                    {/* harness/stages/setup_hooks.py:13-55 — _is_post_edit_command + _ensure_stop_hook
                        dedupe logic keeps re-runs of setup-hooks from stacking duplicate entries. */}
                    Re-running <Code>harness setup-hooks</Code> is safe — the Stop-hook merge
                    dedupes on both the exact command string and any earlier{' '}
                    <Code>harness post-edit</Code> variants.
                </P>
            ),
        },
    ] as EditorialSection[],
};
