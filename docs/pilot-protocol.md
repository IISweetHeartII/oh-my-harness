# Pilot protocol — deciding whether a harness was worth building

A factory that can generate twenty-seven agents is not the same as a factory
that should. This is how a first harness is judged, written down before the
harness exists so the bar cannot move afterwards.

## Before you generate: three conditions, all of them

Run the factory only when **all three** hold. One or two is not enough — the
generated harness will cost more to maintain than the generic agents it
replaced, and nothing will tell you, because a harness that is merely unused
looks identical to one that is working.

| # | Condition | How to check it |
|---|---|---|
| 1 | The same shape of work repeats, at least three times | `git log --format='%s' -200 \| grep -i '^fix' \| grep -oiE '<domain terms>' \| sort \| uniq -c \| sort -rn` — one theme should dominate |
| 2 | At least two roles are genuinely domain-specific | Name them. If you cannot say what each one knows that the generic `executor` does not, there is one role, not two |
| 3 | The output and the stop condition are machine-checkable | A test suite, a schema, an exit code. "It looks right" is not a stop condition |

If any is missing, use the generic agents. Single features, ordinary bugs,
refactors, code review and documentation do not need a harness.

## Worked example: a crawling pipeline

Measured on a real repository (268 tracked files, 200 recent commits):

```
condition 1   'blocking' 11 · 'proxy' 4 · 'timeout' 2 · 'session' 1
              anti-bot drift dominates the fix log        → met
condition 2   blocking analyst / parser repair / canary verification
                                                          → met
condition 3   tests/ with conftest.py, 69 test files       → met
```

All three met, so it is a valid first target. It is also the *safest* first
target: crawl output is deterministic enough to test immediately, and a bad
run costs a re-run rather than money moving.

Do not start with a payments or ledger service. Not because the harness would
be worse there, but because a pilot is where you expect to be wrong.

## Generating

```bash
# a fresh session, with the plugin at the version you intend to evaluate —
# `claude plugin list` must show it, and an update needs a restart to apply
/oh-my-harness:harness build a harness for <domain, one sentence>
```

Declare the namespace first so the naming gate is active during generation
rather than after it:

```json
// .claude/harness.json
{ "agentNamespace": "crawl" }
```

## Judging: five criteria, all of them

A pilot passes only if every line holds. Partial credit is how a harness with
one useful agent and six ornamental ones gets kept.

- [ ] `harness-lint` reports **zero** findings
- [ ] Three real scenarios each route to the correct orchestrator — for a
      crawler: **a new site**, **an expired login**, **a parser drift**
- [ ] **Every generated agent is actually invoked** by at least one of those
      three. An agent no scenario reaches is the thing `orphan-agents` was
      written to find, and a pilot is when it is cheapest to delete
- [ ] One real task runs end to end — local → canary → verified result — with
      **no human fixing the routing** mid-run
- [ ] Against a generic-agent baseline: fewer missed cases, and time and token
      cost up by **no more than 25%**

If any line fails: **delete the generated harness and do not extend to another
service.** The failure is information, and keeping a harness that failed its
own pilot converts that information into maintenance.

## Why the baseline comparison is not optional

Without it the only available conclusion is "it produced something", which is
true of every run. The baseline is what separates *the harness helped* from
*the model would have done that anyway* — and the second is far more common
than it feels, because the harness run is the one you watched.
