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
