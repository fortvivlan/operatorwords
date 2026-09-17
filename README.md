# Operator Words

Python tooling and experiment documentation for multilingual research on operator
words (expletives), conducted with Anton Zimmerling. The current study continues
our comparison of human translations, machine-translation systems, and large
language models.

## Previous paper

A. V. Zimmerling and A. M. Ivoilova, “Operator words versus MT systems and
LLMs,” *Computational Linguistics and Intellectual Technologies*, no. 23,
pp. 471–480, 2025.

```bibtex
@article{циммерлинг2025operator,
  title={Operator words versus MT systems and LLMs},
  author={Циммерлинг, АВ and Ивойлова, АМ},
  journal={Компьютерная лингвистика и интеллектуальные технологии (Computational Linguistics and Intellectual Technologies)},
  number={23},
  pages={471--480},
  year={2025}
}
```

The earlier experiment compared expert translations with outputs from Yandex
Translate, Google Translate, GPT-4o, Gemini 1.5, and
`google/madlad400-3b-mt`. In our working observations, MADLAD-400 did not cope
with Arabic, while Ossetian output was poor across the tested systems.

## Current experiment

The source language is Russian. The target languages are:

- English
- German
- Bulgarian
- Swedish
- Danish
- Icelandic
- Ossetian
- Arabic
- Norwegian (new in this version)
- Finnish (new in this version)
- Hindi (new in this version)

The planned systems are:

- **Google Translate** — collected through the unofficial `googletrans` web
  client because a paid Google Cloud account is not available. The exact client
  version, endpoint, failures, and collection timestamps are retained because
  this route is less stable than the official API.
- **Yandex Translate** — an official Yandex Cloud API exists, but it requires
  Cloud authentication; outputs may instead be collected manually if a
  suitable no-cost API route is unavailable.
- **GPT-6** — translations collected interactively in Codex after selecting the
  GPT-6 model, with the exact prompt and model metadata retained.
- **Gemini 3.8 Flash** — called through the official `google-genai` Python SDK;
  Google AI Studio provides API keys and currently offers a free tier with
  usage limits.
- **TranslateGemma 12B** — the gated
  [`google/translategemma-12b-it`](https://huggingface.co/google/translategemma-12b-it)
  weights run locally after accepting the Gemma licence. Its published coverage
  is 55 languages, so unsupported project languages must be recorded explicitly
  rather than silently substituted.


## Collecting Google Translate output

The Google Translate collector uses the unofficial `googletrans` web client so
that it does not require a paid Cloud account. Install the locked environment and
start the run from PowerShell in the repository root:

```powershell
uv sync --locked
uv run python scripts/collect_googletrans.py
```

Each sentence is submitted in a separate request, with a random delay of 7–9
seconds between requests. Progress is appended to
`data/googletrans-4.0.0rc1-20260917-v1.jsonl`, and the resumable derived table is
written to `data/google_translate.csv`. Ossetian is omitted because `googletrans`
does not support it.

You can stop safely with Ctrl+C. Run the same command to resume; successful
sentence/language pairs are not requested again. If Google returns HTTP 403 or
429, the script stops immediately. Wait several hours (or longer) and run the
same command again. Do not change the run ID, service URL, inputs, delay range,
or retry policy while resuming the same run.
