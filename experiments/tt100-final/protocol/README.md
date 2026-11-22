# Final TT-100 generation protocol

This archive distinguishes the final RTLREX runs (`with_skill`) from the retained
LLM agent baseline runs (`no_skill`). The baseline was not regenerated. Both use
GPT-5.6 Sol, `xhigh` reasoning, a fresh context and a 600-second external generation
limit. The selected protocol fields record the original CLI version, tool
identities, validation limits and parallel execution settings.

## What the files mean

- `with_skill_prompt_template.txt` and `no_skill_prompt_template.txt` are the
  original templates, unchanged. `prompts/<arm>/<case>.txt` contains all 200
  rendered task texts, with hashes verified against the original run summaries.
  `/work`, `/tools`, and `/opt/creas` in these texts are historical sandbox paths,
  not directories in the public checkout. The historical CREAS mount name is
  intentionally preserved for byte identity.
- `with_skill_protocol.json` and `no_skill_protocol.json` are selected extracts,
  not copies of the original protocol files. Each records the original file's
  hash. Private absolute paths are replaced by placeholders. Their exported
  hashes are in the package `SHA256.json`.
- `generic_with_skill/` and `generic_no_skill/` preserve the original generic
  helper sources and their manifests. These are inspection snapshots; they
  expect the original sandbox layout and are not the portable CLI entrypoints.
- `generation_scorers/` contains the two generation-time calculators and weights.
  Baseline generation used an earlier implementation. RTLREX generation used
  the later calculator with revised operand-width and concatenation handling.
  The task texts reflect that difference. They are not byte-identical prompts.
- `../scoring/` contains the single frozen calculator used to score **both**
  sets of final terminal candidates. All reported Q values use this calculator.
- `evaluated_skill_original_manifest.json` is the unchanged manifest of all 137
  evaluated Skill files. `../evaluated_skill/` includes 135 unchanged source and
  instruction files. `evaluated_skill_export.json` records the two omissions:
  machine-local executable configuration and the compiled sampler. The sampler's
  C++ source is included. Root `skills/circuit-reverse-rtl/` is the portable
  installable package and is not claimed to have the historical snapshot's hashes.

The experiment was developed on the same benchmark corpus, rather than an
independent held-out test set. Final RTLREX runs are compared with retained
baseline outputs, not a concurrent randomized two-arm run. Final scoring is
uniform, but the generation-time calculator difference remains a limitation
of causal attribution. No new LLM runs were performed for this release.

## Using the archive

To inspect or recheck reported outputs, use `../check_artifacts.py`. This needs
no model host and preserves every published outcome.

To run a new recovery experiment, configure your own compatible model host,
provide only the selected input in a fresh context, recreate the documented
sandbox/tool access and time limits, and use the corresponding rendered task
text. Match the archived tool versions where exact replication matters. The
historical Skill source requires the documented sandbox layout; the current
portable Skill can be used for a new experiment, with that change recorded.
The archive does not include model credentials, private system/developer
messages, or raw model reasoning. It does not provide a one-command replay of
the original model service or guarantee identical outputs and durations.
