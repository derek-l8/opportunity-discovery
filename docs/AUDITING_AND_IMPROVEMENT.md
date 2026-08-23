# Auditing & improvement

Routine audits **measure, then propose** changes as reviewable diffs. They
never silently self-modify production behavior, and scheduled runs never
rewrite rules/weights/registry.

## Measurements (exact queries against `data/opdisc.sqlite3`)

### Source success / degradation

```sql
SELECT s.source_id,
       SUM(sc.state IN ('healthy','valid-empty')) AS ok,
       SUM(sc.state = 'check-failed')             AS failed,
       SUM(sc.state = 'rate-limited')             AS limited,
       SUM(sc.state = 'format-changed')           AS drift
FROM source_checks sc JOIN sources s ON s.source_id = sc.source_id
GROUP BY 1 ORDER BY failed DESC;
```

Sources failing repeatedly: keep only those with novel value; propose
disabling the rest via registry diff.

### Novel candidate yield per source/cycle

```sql
SELECT p.source_id, COUNT(DISTINCT c.change_id) AS new_leads
FROM changes c
JOIN provenance p ON p.opportunity_id = c.opportunity_id
WHERE c.change_type = 'new'
GROUP BY 1 ORDER BY new_leads DESC;
```

Stale-source rate: sources healthy but zero new leads over a long window:

```sql
-- healthy sources with no first-seen in 60 days
SELECT s.source_id, MAX(o.first_seen) AS newest
FROM sources s
LEFT JOIN provenance p ON p.source_id = s.source_id
LEFT JOIN opportunities o ON o.opportunity_id = p.opportunity_id
GROUP BY 1 HAVING newest IS NULL OR newest < date('now','-60 day');
```

### Duplicate rate and false-merge samples

```sql
SELECT basis, COUNT(*) FROM duplicate_decisions GROUP BY 1;
SELECT * FROM duplicate_decisions ORDER BY decided_at DESC LIMIT 50;
```

Hand-sample merged pairs (`kept_id` vs `merged_id` titles/URLs); any wrong
merge is a bug report against reconciliation — merges must only ever be
identical-normalized-URL evidence.

### Generic filtering errors

Compare `review_queue.jsonl` membership against `reason_codes`: sample
includes/excludes by hand. False includes → tighten family patterns in
`scoring.py`; false excludes → loosen suppression rules. Both are code-review
changes with tests.

### Packet size / run duration trends

`run_summary.json` history + `collection_runs.summary_json`; watch delta packet
`estimated_chars`, page counts, and run wall time.

### Change-detection correctness

Sample recent `changes` rows; for `apparently-closed`, confirm the record is
actually gone from a *successful* live fetch of its source. For
`materially-changed`, diff `changed_fields_json` against reality.

## Improvement loop

1. Measure with the queries above; write findings into an audit note.
2. Propose diffs (code, routing, registry) — small and reviewable.
3. Update fixtures; run `ruff`, `mypy`, full pytest, `opdisc validate-sources`.
4. Record commands + results in `docs/VALIDATION.md`.
5. Only after review do changes enter production configuration.
