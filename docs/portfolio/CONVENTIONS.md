# Shared conventions

Rules every project follows, so the portfolio reads as one body of work and the
"You ship" items (public repo with README, short write-up, live demo or
screenshots) are never an afterthought.

## Repository rules

- **Python 3.11+**, [`uv`](https://docs.astral.sh/uv/) for environments and
  lockfiles, `ruff` for lint and format, `pytest` for tests.
- **Secrets never enter git.** `.env` is gitignored from the first commit.
  `.env.example` contains **only obvious placeholders** (`your-key-here`),
  never real or sample credentials. A secret scanner (`gitleaks`) runs in
  pre-commit and in CI.
- **Sample mode.** Every project has a small committed fixture under
  `data/sample/`. `make test` and CI run on it with no credentials and no
  cloud access. Live-cloud steps are separate targets.
- **Data is not committed**, except `data/sample/`. Raw and processed data
  live in gitignored folders or cloud storage.
- **One `Makefile` per project** with the same verbs: `setup`, `lint`,
  `test`, `ingest`, `demo`, `teardown` (where cloud resources exist).
- **CI per project**, path-filtered so a change in one project does not run
  the others: lint, tests, secret scan.
- **Pin and lock.** Commit the lockfile. Note the date and version of any
  external API behaviour you depend on.

## Documentation rules

Each project has:

| File | Purpose |
| --- | --- |
| `README.md` | What it is, a diagram, results, how to run, demo link, honest status |
| `ARCHITECTURE.md` | Components, data model, decisions and trade-offs, cost, risks |
| `ASSUMPTIONS.md` | Methodology and data assumptions, each with why and how to revisit |
| `docs/decisions/NNNN-title.md` | One short ADR per significant decision (context, options, choice, consequences) |
| `reports/writeup.md` | The short write-up (template below) |
| `docs/img/` | Screenshots used by the README |

**README honesty rule:** describe what exists. Anything not built is under a
"Planned" heading or marked as such.

## Write-up template (`reports/writeup.md`, aim for 1-2 pages)

1. **Question.** What the project answers and for whom, in two sentences.
2. **Data.** Source, coverage, volume, known quirks and gaps.
3. **Architecture.** One diagram and a paragraph.
4. **Decisions and trade-offs.** The 3-5 choices that mattered, each as
   *options → choice → what it cost*. This is the section reviewers read.
5. **Results.** The headline numbers or screenshots, with caveats.
6. **What did not work.** At least one thing, with what you learned.
7. **Cost and operations.** What it costs to run, how it is monitored, how to
   tear it down.
8. **Limitations and next steps.**

## Definition of done (per project)

- [ ] Public repo, README accurate to what is built, diagram included
- [ ] `reports/writeup.md` complete
- [ ] Live demo link, or screenshots in `docs/img/` referenced from the README
- [ ] CI green on a clean clone using sample data only
- [ ] No secrets in the tree or in history (`gitleaks` clean)
- [ ] Cloud resources have a budget alert and a documented teardown
- [ ] Every skill tag the project claims maps to a proof artifact (see
      [`PORTFOLIO_ARCHITECTURE.md`](PORTFOLIO_ARCHITECTURE.md))

## Cost guardrails

- Set a budget alert in each cloud account before creating resources.
- Prefer free tiers and serverless scale-to-zero. Record the actual cost of
  each project in its write-up, even if it is $0.
- Keep a `teardown` target that removes everything the project created.
- Treat all prices and free-tier limits in these docs as unverified until
  checked against the provider's current pricing page.
