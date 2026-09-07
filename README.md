# ko-mt-lint

A linter for Korean text that a machine wrote.

Korean has around two dozen open-source libraries that **generate** the right
particle — `josa`, `k-popo`, `pyjosa`, `Josa.kt`, `kohangul`, and so on. Every
one of them answers the same question: *given a word, is it 은 or 는?*

None of them answer the other one: *here are 70,000 lines a model already
produced — which of them are broken?*

That is what this does.

```console
$ kolint check locale/ko.json --statistics

locale/ko.json:412:18 ERROR KO002 과거 어간 뒤 '는다' -- '했는다' -> '했다'
      하지만 적어도 그녀의 질문은 피했는다.
      fix -> 하지만 적어도 그녀의 질문은 피했다.

locale/ko.json:889:5 ERROR KO102 원문에 없는 한자 문자 '支' (CJK UNIFIED IDEOGRAPH-652F) 혼입
      "支线任务이 너무 많아..." 동료가 중얼거린다.

locale/ko.json:1204:0 ERROR KO005 플레이스홀더 '{name}' 뒤의 '을'는 런타임 값의 받침에 따라
      달라집니다 -- '을(를)' 형태나 조사 처리 헬퍼를 쓰세요
      {name}을 만났다.
```

## Install

```bash
pip install ko-mt-lint
```

No dependencies on Python 3.11+. On 3.9/3.10, add `pip install 'ko-mt-lint[toml]'`
if you want a `kolint.toml` config file.

## Why this exists

Three classes of error survive both a careful prompt and a fast human review.

**Mechanical grammar.** A model picks an ending without checking the syllable
it just wrote. `했는다` stacks a present-tense ending on a past-tense stem —
impossible in Korean, and detectable from the final consonant alone, with no
dictionary and no false positives.

**Pipeline residue.** `/think` tags, `번역:` prefixes, a decoder falling into a
loop, and — the one that really embarrasses a shipped build — another
language's script leaking in. From a corpus of shipped game dialogue:

> `"支线任务이 너무 많아..." 동료가 중얼거린다.`
> `그만해. фаши즘은 객관적으로 나쁘고...`
> `"리كس. 누군가가 할머니를 죽이려고 해."`

Comparing scripts against the source makes this exact.

**Speech level.** Korean grammar forces every sentence to commit to a register —
합니다체, 해요체, 다체, 반말. English does not, so a translator working line by
line has nothing anchoring the choice, and one character drifts across a
conversation. Each line is fine alone; only the group is wrong. Generic i18n
tooling has no concept of this, which is why these rules run over *groups* of
segments rather than one at a time.

## Rules

| Code | Severity | What |
|---|---|---|
| KO001 | error | 조사 중복 (`를을`, `은는`) |
| KO002 | error | 과거 어간 + `는다` (`했는다`, `이었는다`) |
| KO003 | error | 형용사 + `는다/ㄴ다` (`좋는다`, `중요한다`) |
| KO004 | warning | 계사 중복 (`이입니다`) — **opt-in**, 검토 필요 |
| KO005 | error | 플레이스홀더 뒤 받침 의존 조사 (`{name}을`) |
| KO006 | error | 용어집 항목 뒤 조사 불일치 (`성직자을`) — 설정 필요 |
| KO007 | warning | 일반 명사 + 조사 일치 — **opt-in**, 휴리스틱 |
| KO101 | error | 사고 과정 태그 잔여 (`/think`, `<think>`) |
| KO102 | error | 원문에 없던 문자 체계 혼입 (간체자, 가나, 키릴) |
| KO103 | warning | 미번역 통과 |
| KO104 | error | 번역기 메타 발화 잔여 (`번역:`, `Here is ...`) |
| KO105 | error | 동일 토큰/문구 반복 (디코더 붕괴) |
| KO201 | error | 원문 대비 마크업 태그 불일치 |
| KO202 | error | 원문 대비 플레이스홀더 불일치 |
| KO203 | warning | 줄바꿈 개수 불일치 |
| KO301 | warning | 그룹 내 문체 표류 |
| KO302 | warning | 화자 프로파일과 다른 문체 — 설정 필요 |
| KO401 | info | 나레이션 문두 대명사 과잉 (`당신은`) |
| KO402 | warning | 이중피동 (`보여지다`, `되어지다`) |
| KO403 | info | 구두점/공백 위생 |

`kolint rules --all` lists them; `kolint explain KO005` prints the reasoning
behind one.

### The placeholder rule is the one to run first

`{name}을 만났다` is a bug waiting for the first vowel-final name. Nothing can
pick correctly at authoring time, so the answer is a dual form or a
particle-resolving helper — one of those two dozen libraries. **KO005 is the
check that tells you where to call them.**

## Input formats

JSON (nested or flat), JSONL, CSV/TSV, gettext PO, and plain text. Field names
are auto-detected (`source`/`original`/`msgid`, `target`/`translated`/`msgstr`,
`story_name`/`speaker`/`context`), and `--records` addresses nested shapes:

```bash
# [{"story_name": ..., "strings": [{"original": ..., "translated": ...}]}]
kolint check dialogue/ --records '[].strings[]'

kolint check ko.po --select KO2
kolint check strings.csv --source-key en --target-key ko --group-key screen
```

`--fix` writes safe repairs back in place, preserving every other field
(`--diff` shows them without writing). PO files are read-only.

Providing the source text is optional but unlocks KO102, KO103, KO201, KO202
and KO203, and makes KO105 and KO403 considerably more precise.

## Configuration

Optional. `kolint.toml`, discovered by walking up from the working directory:

```toml
[kolint]
extend-select = ["KO004"]
ignore = ["KO401"]
exit-level = "error"          # info | warning | error | never
records = "[].strings[]"

[kolint.KO006]
terms = ["성직자", "코볼드", "은빛 탑"]

[kolint.KO302.speakers]       # 화자별 말투 계약
Archivist  = "formal"         # 합니다체
Envoy      = "polite"         # 해요체
Scout      = "casual"         # 반말
Chronicler = "plain"          # 다체

[kolint.KO102]
allow_han = true              # 한자 병기를 쓰는 프로젝트

[kolint.KO103]
ignore_pattern = "^\\[NOLOC\\]"
```

KO302 turns "how does this character talk" from tribal knowledge held by one
translator into something the build enforces.

## CI

```yaml
- run: pip install ko-mt-lint
- run: kolint check locale/ --format github --exit-level error
```

`--format github` emits workflow-command annotations, so findings land on the
diff. Exit code is 1 when anything reaches `--exit-level` (default `warning`),
2 on a usage or read error.

## Python API

```python
from kolint import lint_text, lint_segments, Segment

for d in lint_text("그는 성직자을 보았는다.", "He saw the cleric."):
    print(d.code, d.message, d.fix)

lint_segments([Segment(target=..., source=..., group="Archivist")])
```

## On precision

Every rule here is written to be quiet rather than clever. Korean is written
without spaces around particles, so a great many "obvious" patterns are
ambiguous with ordinary nouns, and a linter that cries wolf gets turned off.

The rule set was developed against 70,489 machine-translated strings of shipped
game dialogue, and that corpus deleted several rules that had looked fine in
unit tests:

- `과와` as a duplicated particle — **every** occurrence was 치과와, 사과와,
  효과와: a noun plus 와 ("and"). Removed.
- `이입니다` → `입니다` — destroyed `길이입니다` ("it is the length"), because
  길이 is itself a noun. Demoted to opt-in KO004 with a stoplist.
- `을를` → `을` — correctly spots `마을를`, but the repair is `마을을`, not
  `마을`. Removed; KO007 handles it with the noun in hand.
- Repetition detection flagged `"YEEEEEES"` and `사망. 사망. 사망.` until it
  learned to check whether the source repeats too.
- Speech-level detection read `성직자` as 반말, because 자 is also a 해체
  ending. Single-syllable endings now require terminal punctuation.

Those cases are in `tests/test_precision.py`, one test per corpus finding.
The heuristic rules (KO004, KO007) are off by default and say so.

## Development

```bash
pip install -e '.[dev]'
pytest
```

## License

MIT
