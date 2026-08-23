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
    ```bash
    npx truecourse guard
    ```

### View the results

```bash
# browser UI
npx truecourse dashboard

# terminal view
npx truecourse list
```