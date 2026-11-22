# Archived prompt sources

The paper listings preserve source wording and line breaks, replacing every
assigned input and output-directory path by <INPUT> and <OUTPUT_DIR>.

| Listing | Archived source relative to the experiment workspace |
| --- | --- |
| ours_pa30.txt | experimental_results/runs/expansion_37/ICCAD22/test05/rendered_prompt.txt |
| ours_tt100.txt | experimental_results/runs/full_v2/IWLS26/ex200/rendered_prompt.txt |
| no_skill.txt | experimental_results/runs/ablation_no_skill_full/ICCAD22/test01/rendered_prompt.txt |

Other development PA-30 prompts include wording variants and more explicit
allowed-syntax instructions. Missing-wording records:
- experimental_results/runs/expansion_39/ICCAD22/test12/rendered_prompt.txt
- experimental_results/runs/expansion_26/ICCAD22/test28/rendered_prompt.txt

Internal TT runner: experimental_results/scripts/run_iwls_cases.py.
No-Skill scheduling record: experimental_results/ablation_no_skill_protocol.md
(fresh smoke contexts, three reusable lanes in the full run).
The archive does not retain complete runtime system/developer requests.
The current skills/circuit-reverse-rtl/SKILL.md is not claimed to be a
byte-identical copy of all historical Skill versions. Recorded historical
hashes are preserved; unavailable historical wording is not reconstructed.

## Author-confirmed common protocol (2026-09-11)

Both conditions used Codex 5.6, the same calling interface and flow, and
closely aligned task prompts; Skill access was the experimental variable.
This confirmation supplies experiment context absent from the raw logs.
It does not assert invented numeric token/time/tool-call caps or complete
usage traces. See the paper artifact data/ablation_protocol.json (not bundled here).
