# 溯光 · Aletheia Nexus v0.8: ten-paper workflow comparison

[中文主文档](V08_TEN_PAPER_COMPARISON.md) · English translation

This page integrates the latest comparison, completed with source review and deterministic aggregation at 17:15 Singapore time on 2026-10-30, for v0.8 release preparation. **In the supplementary ten-paper view, AN achieved 33/44 strictly correct fields (75.0%), versus 24/44 (54.5%) for native PDF reading in the DeepSeek web application. Its advantage mainly concerned complete experimental conditions and procedures.** Category A tied overall; the web application performed better in B. This does not establish that AN outperforms direct PDF reading for every scientific task.

## 1. Scope and execution status

The batch covers materials, biology, energy catalysis, and environmental separation: ten previously exposed papers and eight research tasks. A organizes literature content; B compares evidence for a research question; C extracts experimental conditions and procedures. Both arms use the same scientific requirements and frozen references. Each of the two B tasks includes two papers and a cross-paper synthesis.

- **AN arm:** original DeepSeek API answers from 2026-10-29 are reused, with model identifier `deepseek-flash`, `reasoning=high`, `source_first/2`, and prompt version `literature-extraction/13`. Papers undergo reading followed by assembly; B also includes cross-paper synthesis. Nine papers use the historical first valid delivery. The tenth, a conductor paper, contributes its originally rejected first response after mechanical, zero-API format compatibility handling and a same-page citation-location correction, as a separate supplementary case.
- **Web arm:** complete PDFs were uploaded natively to DeepSeek on 2026-10-30, producing eight actual answers covering ten papers. The first substantive final answer was fixed. Deep thinking was enabled and intelligent search disabled; the backend model snapshot is unknown.
- **Terminal status:** both arms have completed source review and aggregation. The proposed new paid AN rerun was revoked by the user before launch, and no batch worker remains in flight. Reuse, recovery, and aggregation made no new AN API requests; this does not mean the actual web answers involved no new model calls.

This is a historical workflow comparison, **not a ten-paper unseen holdout evaluation or newly generated scientific performance of the final source revision**.

## 2. Two statistical views

### Preserved primary view: nine historically valid papers

This view excludes the conductor paper that lacked formal historical delivery, preserving the original valid-delivery boundary.

| Metric | AN | DeepSeek web |
|---|---:|---:|
| Strict field precision | 30/40 (75.0%) | 24/40 (60.0%) |
| Strict field recall | 30/40 (75.0%) | 24/40 (60.0%) |
| Required information groups covered and confirmed correct | 65/68 (95.6%) | 58/68 (85.3%) |
| Complete-record correctness | 5/11 (45.5%) | 3/11 (27.3%) |
| Procedure-unit correctness | 5/5 (100.0%) | 2/5 (40.0%) |

### Supplementary view: all ten papers

The additional case contains the same conductor paper's original first response after local compatibility recovery. It was not regenerated, scientifically revised, or selected from competing answers. Historical formal-delivery statistics are not backfilled.

| Metric | AN | DeepSeek web |
|---|---:|---:|
| Strict field precision | 33/44 (75.0%) | 24/44 (54.5%) |
| Strict field recall | 33/44 (75.0%) | 24/44 (54.5%) |
| Required information groups covered and confirmed correct | 70/74 (94.6%) | 60/74 (81.1%) |
| Complete-record correctness | 5/12 (41.7%) | 3/12 (25.0%) |
| Procedure-unit correctness | 6/6 (100.0%) | 2/6 (33.3%) |

Among ten papers, AN has more correct fields in five, the web arm in four, and one ties. Equal-paper mean strict field correctness is 67.1% versus 55.4%. The pooled micro-average gives greater weight to experimental tasks with more fields. In the nine-paper view, the corresponding counts are four, four, and one, with equal-paper means of 66.2% versus 61.6%.

## 3. Three task categories and cross-paper synthesis

The following table uses the supplementary ten-paper view. Categories A and B are unchanged in the nine-paper view.

| Task | Papers | AN strict fields | Web strict fields | AN / web required groups | AN / web complete records |
|---|---:|---:|---:|---:|---:|
| A: literature organization | 2 | 7/8 (87.5%) | 7/8 (87.5%) | 14/14 / 14/14 | 1/2 / 1/2 |
| B: research-question evidence comparison | 4 | 4/12 (33.3%) | 8/12 (66.7%) | 21/24 / 22/24 | 0/4 / 1/4 |
| C: experimental conditions and procedures | 4 | 22/24 (91.7%) | 9/24 (37.5%) | 35/36 / 24/36 | 4/6 / 1/6 |

C procedure units score 6/6 for AN and 2/6 for the web arm. Restricting C to its three historically valid papers gives fields of 19/20 versus 9/20 and complete records of 4/5 versus 1/5.

**Cross-paper synthesis is scored separately:** for hydrogen evolution and oil/water membranes, both arms cover and pass all 6/6 required comparison groups. Whole-synthesis correctness is 0/2 for AN and 2/2 for the web arm. Additional scientific or condition-association errors can still fail an entire synthesis. These scores are not added to the field, information-group, or record denominators above.

## 4. Per-paper results and bibliography

Only bibliographic metadata and metrics are public below; full papers, private raw answers, and local paths are not included. Journal capitalization is normalized from the batch metadata.

| ID / short name | Task | Journal | DOI | AN / web strict fields |
|---|---|---|---|---:|
| P01 ZnCdS/Ni hydrogen evolution | B | ACS Omega | [10.1021/acsomega.0c06038](https://doi.org/10.1021/acsomega.0c06038) | 1/3 / 3/3 |
| P02 TiO₂/C hydrogen evolution | B | RSC Advances | [10.1039/d0ra01322f](https://doi.org/10.1039/d0ra01322f) | 2/3 / 2/3 |
| P03 Chitosan oil/water membrane | B | Environmental Engineering Science | [10.1089/ees.2022.0254](https://doi.org/10.1089/ees.2022.0254) | 0/3 / 1/3 |
| P04 CO₂-responsive membrane | B | Nature Communications | [10.1038/s41467-023-36685-9](https://doi.org/10.1038/s41467-023-36685-9) | 1/3 / 2/3 |
| P05 Self-healing pressure sensor | A | Advanced Science | [10.1002/advs.202200507](https://doi.org/10.1002/advs.202200507) | 4/4 / 3/4 |
| P06 Self-healing polymer electrolyte | C | Nature Communications | [10.1038/s41467-023-43467-w](https://doi.org/10.1038/s41467-023-43467-w) | 7/8 / 6/8 |
| P07 Biodegradable self-healing conductor (supplementary recovery) | C | Science Advances | [10.1126/sciadv.adp9818](https://doi.org/10.1126/sciadv.adp9818) | 3/4 / 0/4 |
| P08 AlbC/CDPS | A | Chemical Science | [10.1039/d2sc01637k](https://doi.org/10.1039/d2sc01637k) | 3/4 / 4/4 |
| P09 GOase/HMF | C | Nature Communications | [10.1038/s41467-021-25034-3](https://doi.org/10.1038/s41467-021-25034-3) | 8/8 / 3/8 |
| P10 Astaxanthin fusion enzyme | C | Synthetic and Systems Biotechnology | [10.1016/j.synbio.2022.10.005](https://doi.org/10.1016/j.synbio.2022.10.005) | 4/4 / 0/4 |

## 5. Delivery failures, scientific errors, and observed cases

The web arm delivered 8/8 tasks and 10/10 papers; AN's historical formal delivery covers 9/10 papers. The conductor's original first raw response was rejected for an extra null-valued member. Local recovery removes only a null extension carrying no scientific information and corrects a same-page citation location. Original scientific values, quotations, and historical answers remain preserved. Current derived results are readable for 10/10 papers; that does not erase the historical failure.

Scientific errors, omissions, and false “not reported” assertions remain in scientific scoring rather than being excluded as technical failures. Every configured field has substantive output, so field precision and recall are numerically identical here. A strict compound field requires its necessary information and object, stage, and condition relations to be complete, including checks of additional scientific content. Passing required groups does not ensure that an entire field or record passes. A single root cause can affect multiple fields; failed-field counts must not be presented as independent root-cause counts.

Source-reviewed differences include:

- For astaxanthin, the web answer reads the main yields but treats a cross-page method as truncated, incorrectly saying that temperature, agitation, secondary seed culture, and YPD composition are unreported. The relevant content appears on main-text page 3; AN retains a more complete cultivation procedure.
- For the GOase scale-up, the web answer omits reported reactor, preactivation, concentration-basis, sampling, and analytical information. AN passes all 8/8 fields for this paper.
- AN also makes real errors: interpreting a chitosan-membrane inset position as a measurement angle; assigning CO₂-responsive membrane adhesion to the wrong state; joining an AlbC PDB identifier to a superscript reference number; and omitting a sample when summarizing TiO₂/C carbon-content ranges.

The batch therefore supports the specific finding that AN delivers more complete complex experimental material, while retaining improvement needs in chart interpretation, condition association, and additional cross-paper inference.

## 6. Materials, cost, and limits of inference

The shared scope comprises 24 PDFs and 319 pages: ten main papers, eight publisher-original PDF supplements, and six complete local DOCX-to-PDF conversions, explicitly labeled as derived reading copies. Three original XLSX files were excluded symmetrically under the pre-answer freeze; not all SI was read. Historical AN inputs contain native text from 316 pages and 319 page images, rendered with `pdftoppm-cropbox-scale1600/v1`. Web attachment bytes and aliases were checked, but internal parsing, image ingestion, and attention to every page are unobservable.

AN reuse, recovery, and aggregation made **0 new paid API requests and incurred 0 new API cost**. Historical selected AN tasks, deduplicated across 14 call owners, retain 27 HTTP attempts including failures and recovery, 3,307,550 input and 670,185 output tokens, a time-dependent estimate of **CNY 10.63738256**, and zero unknown-usage calls. This is a historical estimate, not a new charge or provider bill. Summed historical call duration is approximately 3,637.8 seconds and is not user waiting time. Web tokens, fees, and complete manual-upload time are unavailable, preventing matched cost or speed comparisons.

Scoring uses assistant original-source review, with independent aggregation and consistency checks; **it is neither expert human gold nor double-blind evaluation**. All emitted scientific content and absence assertions are checked. Conflicting source readings remain distinguished, and lenient sensitivity readings do not replace the main scores. All ten papers were previously exposed, the sample is small, and C contains more fields. Different dates, model snapshots, call counts, and output contracts mean these results describe the observed workflows; they cannot isolate a causal gain from the parser or a specific strategy.

## 7. Release integration and audit fingerprints

This batch integrates results and conclusions only. It introduces no product patch and changes no historical reference, original answer, denominator, or formal-delivery count. Its comparison worktree is fixed at `0f297e525427a17f989c6ed266ae9b42a999e3f9`; no additional product-code merge is required from that tree, and this comparison alone does not change default strategies. It does not replace engineering acceptance of the final integrated version or unseen-paper generalization findings.

The private `release-native-pdf-comparison-20261030` audit directory retains freezes, raw-answer indexes, source reviews, and cost ownership. To avoid redistributing full papers or private answers, the public repository includes this summary and the following fingerprints only:

| Evidence | SHA-256 |
|---|---|
| `aggregation/comparison-summary.json` | `49af871ee4ead45a872538f65ebfa7e0c6e89b9428df5fb25dd29c9560057a46` |
| `root-web-execution-freeze.json` | `18a16baa6f4fcab89bce4e7dce5ed19f075a6d2c45903df8ace77082ebb2d04a` |
| `aggregation/integrity-proof.json` (114 bindings) | `1b1fd3b021cea5520e96079e14526286d8ab9ca7355ffbb095155ebf70f57432` |

These fingerprints permit comparison with a copy of the original audit materials; they do not imply that those complete materials are present in the public repository.
