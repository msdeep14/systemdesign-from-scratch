# Architecture Guardrails

Configurations related to enforcing architectural boundaries in the Photoz.

## Structurizr (C4 Model)

Uses the C4 model for documenting its software architecture as code. The architecture is defined in `photoz/structurizr/workspace.dsl`.

### How to Run and Test Locally

For local viewing, cd to `photoz` directory and run the **Structurizr vNext** Docker container:

```bash
cd photoz
docker run -it --rm -p 8080:8080 -v $(pwd)/structurizr:/usr/local/structurizr structurizr/structurizr local
```

After the container starts, type in below url in web browser:
`http://localhost:8080`

Any changes you make to `workspace.dsl` will be reflected in the browser.

### Level 4 (Code) View

Structurizr intentionally omits the "Code" level of the C4 model as it is best auto-generated directly from source code to avoid maintenance drift. To generate an ER diagram of all Django models and their relationships:

1. **Install Prerequisites:**
   Ensure you have `graphviz` installed on your system (e.g., `brew install graphviz`).
   The required python packages (`django-extensions` and `pydot`) are already in `requirements-dev.txt`.

2. **Generate the Diagram:**
   ```bash
   cd photoz
   source venv/bin/activate
   python manage.py graph_models -a -o models_code_view.png

   # for user model 
   python manage.py graph_models users -o user_model.png 
   ```
   This will output `models_code_view.png` in the `photoz` directory containing the full schema.

## Import Linter

We use `import-linter` to strictly enforce domain boundaries between Django apps (e.g., preventing `newsfeed` from tightly coupling with `users` or `communities`). The configuration is stored in `photoz/.importlinter`.

### How to Run and Test Locally

The import linter is automatically executed on every commit via `pre-commit`. However, to run it manually against all files:

```bash
cd photoz
pre-commit run import-linter --all-files
```

If it detects an architectural violation (e.g. an unauthorized cross-app import), the commit will be blocked and the offending lines will be printed to the console.

## TrueCourse (AI Architecture Guard)

TrueCourse is an AI-powered architecture analysis and code intelligence platform. It complements the `import-linter` by analyzing semantic layer violations, business-logic drift, and detecting if the code deviates from our specs (ADRs/PRDs) using a local LLM.

To avoid API keys and cloud dependencies, we run TrueCourse strictly using **Ollama** running locally on your laptop.

### 1. Prerequisites Setup

Since TrueCourse is distributed as an `npm` package, you must first install Node.js and Ollama.

1. **Install Node.js (if not installed):**
   ```bash
   # Install via Homebrew on macOS
   brew install node
   ```
   Verify installation: `npm -v`

2. **Install Ollama:**
   Download and install Ollama from [ollama.com](https://ollama.com).

3. **Pull Local LLMs:**
   Once Ollama is installed and running (you should see the Ollama icon in your Mac menu bar), open your terminal and pull our required models. We use Llama 3.1 for general reasoning and Qwen 2.5 Coder for deep code analysis:
   ```bash
   ollama pull llama3.1:8b
   ollama pull qwen2.5-coder:7b
   ```

* llama3.1:8b consumed around 11GB RAM on my machine while running, so be ready :D

### 2. TrueCourse Configuration

Once the prerequisites are installed, you must initialize TrueCourse in the `photoz` directory and point it to your local Ollama API.

1. **Initialize TrueCourse:**
   Navigate into the `photoz` directory and run the initialization command:
   ```bash
   cd photoz
   npx truecourse analyze install
   ```
   During the installation prompt, select the following options to wire it to Ollama:
   * **How should TrueCourse run its LLM calls?** -> `API — bring your own key`
   * **Which provider?** -> `OpenAI` *(Ollama natively mimics the OpenAI API format)*
   * **Which model?** -> `llama3.1:8b` *(or qwen2.5-coder:7b)*
   * **API key** -> `OLLAMA_DUMMY_KEY` *(Ollama does not check this)*
   * **Fallback model** -> *(Leave blank)*
   * **Set an advanced option?** -> `Yes`
   * **Base URL** -> `http://localhost:11434/v1`
   * **Would you like to install Claude Code skills?** -> `No`

   You can change model using `truecourse config llm setup`.

   *This will create a `.truecourse` directory to store JSON configurations and analysis results.*

2. **Configure Local LLM Endpoint (Headless/CI):**
   If you ever need to script this configuration non-interactively (e.g. bypassing the prompt above), you can run this exact command:
   ```bash
   npx truecourse config llm setup --transport api --provider openai --model llama3.1:8b --api-key-env OLLAMA_DUMMY_KEY --base-url http://localhost:11434/v1
   ```

### 3. Execution

You can now run TrueCourse to analyze the architecture and detect semantic drift:

*   **Analyze Structural Code Defects:**
    ```bash
    npx truecourse analyze
    ```
*   **Guard Business-Logic (Check specs against code):**
    Because `truecourse guard` dynamically verifies your code against your documentation, it requires a series of steps to scan your docs, resolve conflicts, and run tests:
    ```bash
    # 0. Set up the environment and recipe.json
    npx truecourse guard setup -y

    # 1. Scan documentation and C4 models to build the spec corpus
    npx truecourse spec scan

    # 2. List and resolve any conflicting documentation 
    npx truecourse spec conflicts list
    npx truecourse spec conflicts resolve 1 --right README.md

    # 3. Generate end-to-end scenario tests based on your documentation
    npx truecourse guard generate -y

    # 4. Boot the app (via recipe.json) and run the scenario tests
    npx truecourse guard run
    ```

    **TrueCourse Observations & Limitations**

    TrueCourse is new and not fully mature. The documentation on GitHub `main` describes features not yet in the stable `npm` release. Install the pre-release tag to use them:
    ```bash
    npm install -g truecourse@0.8.1-next.0
    ```

    **1. Local Model Support**
    Local models like `qwen2.5-coder:7b` parse JSON successfully. Ensure `recipe.json` uses `"cwd": "repo"` and the correct `python` binary to prevent sandbox crashes.

    **2. Setup Command & "0 Tables"**
    `npx truecourse guard setup` will report `0 tables`. This is expected. TrueCourse cannot parse Django's `models.py`. Bypass this by calling your seed script in the `recipe.json` `build` command.

    **3. Flow Synthesis Failures**
    TrueCourse relies on LLMs to synthesize test flows. Small local models (7B/8B) often hallucinate flows (e.g., trying to test internal concepts like the "Redis Lock Cache Promise") and crash the synthesis stage.
    *Recommendation:* Use higher parameter models like **Gemini 3.6 Flash** via LiteLLM for the generation phase. They can distinguish architectural concepts from testable HTTP endpoints.
    To set this up:
    1. Get a [Gemini API Key from Google AI Studio](https://aistudio.google.com/app/apikey).
    2. Start the LiteLLM proxy:
       ```bash
       pip install 'litellm[proxy]'
       GEMINI_API_KEY=your_key litellm --model gemini/gemini-3.6-flash
       ```
    3. Configure TrueCourse (`npx truecourse config llm setup`): 
       - Provider: `OpenAI`
       - Model: `gemini/gemini-3.6-flash`
       - Base URL: `http://localhost:4000`

    **4. The Django "no journey" Limitation**
    TrueCourse drops correctly generated API flows (e.g. Signup, Login) reporting `no journey`. It maps documented flows to code using AST parsing, but our direct analysis of the TrueCourse source code (`cli.mjs`) revealed exactly why it fails for Django:
    - The Python route extractor (`extractPythonRoutes`) hardcodes a regex that searches exclusively for decorator-based routing: `decoratorText.match(/@\w+\.(get|post|put|delete|patch|route)\s*\(/)`.
    *Conclusion:* TrueCourse cannot currently map journeys for Django applications. Its AST parser only supports Python applications built with **FastAPI or Flask**. It is structurally incapable of parsing Django's `urlpatterns` list, meaning it assumes the documented endpoints simply don't exist in the codebase.

### View the results

```bash
# browser UI
npx truecourse dashboard

# terminal view
npx truecourse list
```

## Drift (Architectural Erosion Check)

Drift (`drift-analyzer`) is a static analysis tool and GitHub Action designed to detect "architectural erosion" and structural drift in codebases. It natively analyzes structural ASTs, Git commit histories, and import patterns.

Drift helps maintain the architectural integrity of Photoz by detecting:
* **Hidden Co-Change Coupling:** Identifying files that change together frequently without explicit dependencies.
* **Pattern Fragmentation:** Detecting slightly different variants of the same design pattern across apps.
* **Novel Dependencies:** Flagging when apps start importing dependencies they historically haven't used.

### 1. Installation

Drift is distributed via PyPI. We install it into our existing python virtual environment.

```bash
# From inside the photoz directory with venv activated
pip install drift-analyzer
```

### 2. Local Usage

To manually check for structural drift or architectural violations during development, use the CLI:

```bash
cd photoz

# View the traffic-light status of the repository
drift-analyzer status

# Get a detailed analysis with all structural findings
drift-analyzer analyze --repo .
```

### 3. GitHub Action

This is configured at `.github/workflows/drift.yml`:
