# Corpus Atelier

Corpus Atelier is a local, AI-assisted graphic-design studio built from two cooperating layers:

- **corpus** — a local-first archive of traceable prompt↔image records, with a closed visual taxonomy and SQLite full-text retrieval.
- **atelier** — the generation pipeline that turns a natural-language request into visual directions, design proposals, and one renderer-ready image prompt for GPT Image 2 / 2.5, with reference-image editing, mask inpainting, and a post-generation checklist.

Natural-language interaction runs through the whole flow: describe a goal, review and approve the prompt that will be sent, generate and select images, then optionally archive the results you like back into the corpus. A precise request can skip direction exploration and go straight to one reviewed prompt, and writing that prompt may draw on similar archived corpus entries as advisory references. It is suitable for posters, article covers, social-media graphics, invitations, labels, album covers, and other graphic-design tasks, under one general design objective: the brief decides how much weight the design gives to communication and to visual quality.

## Install

Corpus Atelier runs locally. You will need Git, Python 3.10 or later, and an OpenAI API key.

### Windows

```powershell
git clone https://github.com/666feiyu666/corpus-atelier.git
cd corpus-atelier

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt

# Terminal 1 — the Python boundary
corpus-atelier api --host 127.0.0.1 --port 8787

# Terminal 2 — the interface (Node 20 or later)
cd web
npm install
npm run dev
```

### macOS

```bash
git clone https://github.com/666feiyu666/corpus-atelier.git
cd corpus-atelier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt

# Terminal 1 — the Python boundary
corpus-atelier api --host 127.0.0.1 --port 8787

# Terminal 2 — the interface (Node 20 or later)
cd web
npm install
npm run dev
```

Corpus Atelier opens in your browser. On first use, open **Settings** and enter your OpenAI API key. Finished designs can be archived into the **Corpus** view; archived prompts and reference images become searchable references for future work.

## Tests

```bash
python -m unittest discover -s tests -t .
```

Architecture diagrams live under `docs/diagrams/`.
