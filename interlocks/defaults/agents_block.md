<important if="you need to run quality gates, tests, or inspect config">

| Command | What it does |
|---|---|
| `interlocks check` | Run after edits |
| `interlocks pre-commit` | Pre-commit stage (auto via hook) |
| `interlocks ci` | PR/CI stage |
| `interlocks nightly` | Nightly cron stage |
| `interlocks setup` | Install local hooks, agent docs, Claude skill |
| `interlocks setup --check` | Verify local integrations read-only |
| `interlocks help` | List subcommands + thresholds |
| `interlocks config` | List config keys + resolved values |
</important>
