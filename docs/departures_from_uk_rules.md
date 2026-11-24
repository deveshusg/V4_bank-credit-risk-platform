# Departures from UK rules

The loans are US conforming residential mortgages from Fannie Mae, assessed under UK rules.

All work follows UK rules. The data that goes with the loans (interest rates,
unemployment, house prices) is US, because the loans are US (decision D-025). This file
lists every place where a UK rule meets US data, so the gaps are known before any number
is read.

Each entry gives the UK rule with its words, what we do, why, and the likely effect.

Sources were read on 15 November 2026 from the PRA Rulebook and the Bank of England
website. The quotes came through a web page reader, so check the exact wording against
the source before quoting it outside this project. Versions read:
- PRA Rulebook, "Credit Risk: Internal Ratings Based Approach (CRR)" Part and "Credit Risk
  Mitigation (CRR)" Part: the versions that take effect on 1 January 2027. Article
  numbers below refer to these Parts. The rules in force before that date were not read.
- SS11/13 "Internal Ratings Based (IRB) approaches": version of 1 January 2022. 13.13 to
  13.13B were read on the Rulebook page dated 3 September 2025; 10.4, 10.12 and 13.9 on the
  page dated 1 January 2022.
- Quotes not yet checked word for word against the page are marked so in each entry and
  in the Sources table at the end.
- PS9/24: published 12 September 2024.

| No. | Departure | Where it shows |
|---|---|---|
| 1 | The loans are US mortgages | All modules |
| 2 | LGD discount rate built on the federal funds rate, not SONIA | macro_economic_mart |
| 3 | Monthly average rate, not the rate on the day of default | macro_economic_mart |
| 4 | Downturn discount rate is the higher of 9% and the long-run rate | macro_economic_mart |
| 5 | US unemployment and US house prices are the economic drivers | macro_monthly_table |
| 6 | US state house price index used to update property values | macro_state_hpi_table |
| 7 | SS4/24 paragraph numbers not yet confirmed; SS11/13 is cited | All citations |
| 8 | October 2025 unemployment is blank in the source file | macro_monthly_table |

## 1. The loans are US mortgages

UK rule. PRA Rulebook IRB Part, Article 179(1)(d): "the population of exposures
represented in the data used for estimation, the lending standards used when the data
was generated and other relevant characteristics shall be comparable with those of the
institution's exposures and standards." SS11/13 10.12 asks a firm using external data to
consider "whether the data are appropriate to its own experience and whether adjustments
are necessary." (Both quotes not yet checked word for word.)

What we do. Every model is built on Fannie Mae loans (2000 to 2025) and judged against
UK rules. There is no UK bank book to compare the data with.

Why. Fannie Mae publishes full monthly loan histories. We know of no public UK
loan-level history of the same length and depth.

Likely effect. Results describe US borrowers, US lending standards and US arrears and
repossession law. They show how a UK bank would build and check the models. They are not
estimates for a UK mortgage book.

## 2. LGD discount rate built on the federal funds rate, not SONIA

UK rule. SS11/13 13.13A: "the PRA expects firms to use a discount rate of Sterling
Overnight Index Average (SONIA) at the moment of default plus 5% for exposures
denominated in GBP." For other currencies, "firms should use a comparable liquid
interest rate in the currency of that exposure."

What we do. Long-run discount rate = the effective federal funds rate + 5% (FRED series
FEDFUNDS).

Why. The loans are in US dollars, so the currency clause applies. Like SONIA, the
federal funds rate is an unsecured overnight rate, and it covers 2000 to 2026. SOFR is
secured and starts only in April 2018, so it cannot cover earlier defaults. A sterling
rate (SONIA or Bank Rate) on dollar cash flows would go against the currency clause.

Likely effect. The discount rate follows US policy rates, not UK ones. Where US rates
were higher than UK rates the discount is larger and the LGD higher, and the other way
round. We have not measured the gap.

## 3. Monthly average rate, not the rate on the day of default

UK rule. SS11/13 13.13A takes the rate "at the moment of default" (quoted in entry 2).

What we do. FEDFUNDS is a monthly average of daily rates. We keep one rate per calendar
month and join it on the month of default (not the reporting month).

Why. The monthly series is public, simple and covers the full period. The loan data is
monthly, so the default date is known only to the month.

Likely effect. Small when rates are steady. In a month with a rate change, the gap can
be as large as part of that change.

## 4. Downturn discount rate is the higher of 9% and the long-run rate

UK rule. SS11/13 13.13: "firms should ensure that no discount rate used to estimate
downturn LGD is less than 9%." SS11/13 13.13B sets the same 9% floor for LGD in-default (paraphrase, not read word for
word).
PS9/24 3.141: "for the purpose of downturn LGD, the PRA expects firms to use a discount
rate of at least 9%." A source check reported that PS9/24 3.141 also calls an earlier
"higher of 9% and SONIA plus 5%" wording an error. That sentence has not yet been read
word for word.

What we do. Downturn discount rate = the higher of 9% and the long-run rate.

Why. It meets the 9% floor and stops the downturn rate falling below the long-run rate.
This is our own stricter choice, not the PRA's wording.

Likely effect. On today's files the downturn rate is 9.00% in 245 of 322 months (244
months with the federal funds rate below 4% and 1 month, 2005-11, at exactly 4.00%). In
the other 77 months the federal funds rate is above 4%, and the downturn rate is above 9%.
In those months downturn LGD is higher than a flat 9% would give.

## 5. US unemployment and US house prices are the economic drivers

UK rule. PRA Rulebook IRB Part, Article 181B(1), lists the economic indicators to use
when identifying an economic downturn. For all exposures these include "gross domestic
product;" and "unemployment rate;". For retail exposures secured by residential
property they add "house prices or house price indices;". Article 181B(2) says the indicators should "reflect the
geographical distribution" of the exposures. (Quotes not yet checked word for word.)

What we do. We use the US unemployment rate (FRED UNRATE) and the FHFA house price index
(national monthly and state quarterly). No UK series is used. GDP is not loaded yet.

Why. The loans are in the US, so the indicators of the place where the loans are follow
Article 181B(2).

Likely effect. The downturn follows the US cycle (for example the 2007 to 2011 US house
price fall), not the UK cycle. Without GDP, the indicator set is not yet the full list in
Article 181B(1).

## 6. US state house price index used to update property values

UK rule. No UK rule read so far names an index or a geography. PRA Rulebook Credit Risk
Mitigation Part, Article 208(3) (version of 1 January 2027; the source check read it as
point (b)): "The institution may use statistical methods to monitor the value of the
immovable property and to identify immovable property that needs revaluation." SS11/13
13.9 refers to adjusting house prices "with reference to appropriate house price
indices", through a formulaic process. (Both quotes not yet checked word for word.)

What we do. Property values are to be updated with the FHFA state purchase-only house
price index (quarterly, seasonally adjusted).

Why. The loan data gives the state of each property. A state index is the finest public
series that covers 2000 to 2026 for every state.

Likely effect. A state index misses moves inside a state (city or area level). It is
quarterly, so moves within a quarter are missed. Property values, and so LGD, may be
over- or under-stated for loans in areas that moved unlike their state.

## 7. SS4/24 paragraph numbers not yet confirmed; SS11/13 is cited

UK rule. SS4/24 "Credit risk internal ratings based approach" (Bank of England, first
published 12 September 2024, updated 20 January 2026) takes effect on 1 January 2027.

What we do. We cite SS11/13 13.13, 13.13A and 13.13B and PS9/24 3.141, which were read.
SS4/24 is named as the successor but is not cited by paragraph.

Why. The SS4/24 PDF could not be opened by any tool here, so its paragraph numbers and
words have not been read.

Likely effect. When SS4/24 takes effect, the citations must be checked against it by
hand. The wording or numbers may differ.

## 8. October 2025 unemployment is blank in the source file

UK rule. PRA Rulebook IRB Part, Article 174(b): a firm "shall have in place a
process for vetting data inputs into the model, which includes an assessment of the
accuracy, completeness and appropriateness of the data;". SS11/13 10.4 asks for
"reasonable assurance that data input into the rating system is accurate, complete and
appropriate." (Both quotes not yet checked word for word.) No UK rule read so far says how to treat a single missing month.

What we do. The month stays blank and is flagged (unemployment_missing = TRUE). Any
change that spans it is blank. Nothing is filled in. A later module decides how to fill
it, and says so.

Why. A filled month would look like real data. Leaving it blank and flagged keeps the
gap visible to every later check.

Likely effect. On today's files four values are blank: the 1-month and 12-month
unemployment changes for 2025-10, the 1-month change for 2025-11 and the 12-month change
for 2026-10. Loans observed in those months have no value for those fields until a later
module fills them.

## Sources

All read on 15 November 2026. Rows marked "no" came through a web page reader and must be
checked against the page word for word before use outside this project.

| Citation | Version | Checked word for word | Link |
|---|---|---|---|
| SS11/13 13.13, 13.13A, 13.13B | 1 January 2022 (page view 3 September 2025) | 13.13 and 13.13A yes; 13.13B paraphrased | https://www.prarulebook.co.uk/guidance/supervisory-statements/ss11-13--internal-ratings-based-irb-approaches/03-09-2025 |
| SS11/13 13.9 | 1 January 2022 | no | https://www.prarulebook.co.uk/guidance/supervisory-statements/ss11-13--internal-ratings-based-irb-approaches/13-loss-given-default-in-irb-approaches/01-01-2022 |
| SS11/13 10.4, 10.12 | 1 January 2022 | no | https://www.prarulebook.co.uk/guidance/supervisory-statements/ss11-13--internal-ratings-based-irb-approaches/10-overall-requirements-for-estimation/01-01-2022 |
| PS9/24 3.141 ("at least 9%") | 12 September 2024 | the "at least 9%" sentence yes; the "error" sentence not read | https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2 |
| IRB Part Art 174(b) | 1 January 2027 | no | https://www.prarulebook.co.uk/pra-rules/credit-risk-internal-ratings-based-approach-crr/3-credit-risk-internal-ratings-based-approach-crr-part/article-174-use-of-models/01-01-2027 |
| IRB Part Art 179(1)(d) | 1 January 2027 | no | https://www.prarulebook.co.uk/pra-rules/credit-risk-internal-ratings-based-approach-crr/3-credit-risk-internal-ratings-based-approach-crr-part/article-179-overall-requirements-for-estimates/01-01-2027 |
| IRB Part Art 181B(1), (2) | 1 January 2027 | no | https://www.prarulebook.co.uk/pra-rules/credit-risk-internal-ratings-based-approach-crr/3-credit-risk-internal-ratings-based-approach-crr-part/article-181b-economic-downturn-relevant-indicator-set/01-01-2027 |
| CRM Part Art 208(3) | 1 January 2027 | no; point letter not confirmed | https://www.prarulebook.co.uk/pra-rules/credit-risk-mitigation-crr/3-credit-risk-mitigation-chapter-4-of-title-ii-of-part-three-of-crr/article-208/01-01-2027 |
| SS4/24 (effective date only) | updated 20 January 2026 | page read; PDF not opened | https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/credit-risk-internal-ratings-based-approach-supervisory-statement |
