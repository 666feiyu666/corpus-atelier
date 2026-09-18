# Pilot 2: local reference images

This pilot uses a small local Mucha corpus to create aesthetic cover and inline images for WeChat articles. It does not analyze article text. Pilot 1 remains unchanged.

## Run

From the repository root, with the project environment active:

```powershell
python -m pip install -e ".[notebook]"
python experiments/pilot2/create_corpus.py
python -m jupyter lab experiments/pilot2/reference_images.ipynb
```

Set `OPENAI_API_KEY` in the repository's local `.env` or the launching environment. The notebook loads `.env` without overriding an existing process variable. Its generation cell defaults to `GENERATE = False`; review the selected references and exact prompt before changing it to `True`.

The notebook lets you browse by visual words, choose one to three references, preview a cover or illustration request, generate one image, and compare saved attempts. Every image call saves its request, source references, hashes, prompt, status, and PNG under `experiments/pilot2/outputs`. The cover and illustration sizes are pilot presets; inspect the final crop in the publishing editor.

## Local corpus and rights

`create_corpus.py` imports seven pinned Mucha works from the Cleveland Museum of Art Open Access API. It checks that each current record identifies Mucha, has an image, and reports `CC0`. The local `corpus` directory holds the downloaded images and a manifest with source pages, license links, and SHA-256 hashes. This checkout excludes the entire directory through `.git/info/exclude`; it is not uploaded to the remote. Do not add it with `git add -f`.

The museum's [Open Access policy](https://www.clevelandart.org/open-access) explains the image terms. Review generated images for close copying, lettering, signatures, or logos from a source. Do not imply museum endorsement. Selected reference files leave the local machine only when a generation request sends them to the configured image API.
