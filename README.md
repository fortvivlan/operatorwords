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

- **Google Translate** — collected through the official Google Cloud
  Translation API and its Python client, subject to credentials, quotas, and
  billing.
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

All project code should be Python (`.py`). Prefer a project-local virtual
environment managed with [uv](https://docs.astral.sh/uv/). Raw source documents,
translations, credentials, and generated experiment data belong under `data/`,
which is intentionally excluded from Git. API secrets must be supplied through
environment variables and never committed.

For reproducibility, each result should preserve the source sentence and stable
ID, target language, provider, exact model/version where exposed, prompt or API
settings, raw output, collection timestamp, and any error or unsupported-language
status.
