# Lessons Learned Building Frederick Signal Atlas

Frederick Signal Atlas started as a simple idea: fetch Frederick-related news every day, extract the people mentioned, and gradually build a local civic relationship database. In practice, the hard part was not storage, scheduling, or even article collection. The hard part was deciding what *counts* as a person record worth keeping.

## Lesson 1: Source quality matters more than extraction cleverness

The first runs used an aggregated Google News RSS source alongside official Frederick feeds. That looked attractive because it increased article volume quickly. In reality, it polluted the pipeline.

- Some Google News entries resolved to wrapper pages instead of the publisher article.
- Some resolved only to a publisher homepage rather than the specific story.
- The extractor then read unrelated page furniture, navigation, promos, and “top stories” blurbs.

That failure mode created a false impression that the extraction logic itself was broken. It was partly broken, but the upstream source quality was the larger issue. Once the default source set was narrowed to official Frederick city and county feeds, the database immediately became more trustworthy even before the extractor got smarter.

The practical takeaway is simple: in a civic intelligence pipeline, one clean source is often worth more than ten noisy aggregate sources.

## Lesson 2: Zero names was safer than bad names, but not useful enough

After the early noisy runs, the pipeline was hardened aggressively. Low-confidence fallback matches were filtered out, and the result was a database that often recorded no people at all.

That was safer than storing garbage, but it was also too conservative for a bootstrapping phase. A new database needs enough recall to accumulate signal over time, especially when many official public notices mention only a small number of people.

The better balance was:

- allow more borderline full-name matches into the pipeline
- keep them clearly marked with lower confidence
- infer nearby role, organization, address, and location context
- use that context to decide whether a candidate is worth storing

In other words, the system needed a bootstrap mode rather than a binary “strict or useless” mode.

## Lesson 3: Confidence should come from evidence, not only from model trust

The fallback extractor originally gave every accepted name roughly the same confidence. That made it impossible to separate “Joshua Masser, Historic Preservation Planner at 301-600-6242” from “Additional Information.”

The fix was heuristic confidence scoring based on evidence present in the article:

- repeated mentions
- nearby role text
- nearby organization text
- address context
- contact cues like phone numbers or email addresses

That shifted the pipeline from “string matching with a threshold” to “evidence-backed bootstrapping.” Once that happened, real people such as Joshua Masser, Sean Coughlin, Kelley Berliner, Christina Martinkosky, Laila Jadallah, and Jason Blake began to surface more reliably.

## Lesson 4: Organization names are the main enemy of person extraction

Government and civic articles contain many capitalized phrases that look person-like to a regex:

- commissions
- departments
- councils
- cultural initiatives
- venues
- street names
- heritage groups
- alert programs

These phrases are especially dangerous because they often sit near genuine people and legitimate public metadata. A naive extractor happily turns them into person rows.

The pipeline improved once it started combining:

- token-level stopword filters
- first-token and last-token exclusions
- role-prefix normalization
- organization-suffix blocking
- record-level plausibility checks

This was more effective than adding one giant blacklist because it attacked the problem structurally.

## Lesson 5: Reprocessing is essential

A daily collection system is not static. Source quality changes, extraction rules change, and confidence logic changes. If the database never reprocesses old articles after those changes, earlier mistakes stay frozen forever.

That is why the pipeline was updated to re-queue articles when:

- fetched content changes
- the extraction method changes
- source strategy changes enough to justify another pass

Without reprocessing, every improvement is only prospective. With reprocessing, the database can gradually become cleaner over time.

## Lesson 6: “Interesting connections” should lag behind extraction maturity

Relationship reports are compelling, but they amplify upstream errors. A bad extractor does not just create one bad person row. It creates many bad pairwise links.

That means connection analysis should be downstream of person quality, not parallel to it. In this project, the safest path was:

1. clean sources
2. better person extraction
3. confidence-based storage
4. only then, stronger connection reporting

Otherwise, a visually persuasive network graph becomes a machine for laundering extraction mistakes into false narrative.

## Lesson 7: Official sources are narrow, but they are valuable

Official city and county feeds do not produce a huge daily volume. Some days they produce no personal records at all. That is not failure. It reflects the nature of the source set.

The upside is that when they *do* include people, those mentions are often unusually useful:

- named officials
- program managers
- departmental contacts
- organizers
- public safety contacts
- addresses tied to civic functions

That makes official sources excellent backbone data, even if a later phase adds carefully selected publisher feeds for broader coverage.

## What Changed in Practice

The project improved by making a few non-obvious but important moves:

- removed Google News from the default source list
- lowered the bootstrap threshold instead of demanding near-perfect confidence
- attached local context to every fallback name candidate
- scored candidates using evidence rather than treating all matches equally
- filtered organization-like names more aggressively
- reprocessed recent official articles after every major extractor improvement

Those changes turned the system from “either noisy or empty” into something more useful: a cautious but growing Frederick civic people database.

## The Main Takeaway

The biggest lesson is that early-stage civic knowledge systems should optimize for *traceable plausibility*, not raw volume and not perfect precision.

You want records that are:

- sourced
- inspectable
- revisable
- confidence-scored
- easy to reprocess when your extraction logic improves

That is how a local public-information database becomes dependable over time.
