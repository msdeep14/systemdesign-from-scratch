# AI Agent Instructions

This document contains guidelines on AI agent response generation, coding standards, and execution mandates for all the work done in repository systemdesignfromscratch. **All AI coding agents MUST read and adhere to these guidelines when responding to queries or making changes or additions in the codebase.**

## 1. Execution Logging Mandate for code execution/ implementation plan generation only (CRITICAL)
* Whenever you perform analysis, make architectural/design decisions, or take implementation actions, **you MUST append a log of your work to `execution-{version}.md`** where {version} is the current version of the codebase. The file should be created if it does not exist. The location of file is specific chapter being worked upon. Example : `chapter01/execution-v0.md`.
* Similarly, any implementation plan generated should be added to `implementation-{version}.md`. Location is same as above. Example : `chapter01/implementation-v0.md`.
* The entry in each of these logs should include:
    * The phase or feature you are working on.
    * Brief analysis and the rationale behind any technical decisions made.
    * A bulleted list of specific actions taken (files created, models updated, bugs resolved).
    * Any notable edge cases or errors you encountered and how you fixed them.

## 2. Coding Standards
- **Keep it Simple & Direct**: Do not over-engineer. Do not abstract for the sake of abstraction. If a feature can be implemented cleanly in 10 lines instead of 100, choose the 10-line approach.
- **Strict Scope**: Do not add features or "future-proofing" abstractions that are not explicitly required for the current version.
- **Self-Documenting Code**: Avoid unnecessary comments. Code structure, method names, class names, and database schemas should be self-explanatory. Only add comments for highly complex logic.
- **Ask for Clarification**: Do not make blind assumptions. If the user's request is ambiguous or underspecified, stop and ask for clarification.

## 3. LLM Response Generation
* LLM should respond in a human like manner. 
* LLM should not respond with a very long text. It should respond with a concise text.
* Avoid saying 'this is great question' or 'this is great idea' or 'that is a great question' or 'that is a great idea'.
* Be critical in the responses. Don't just agree with the user. 
* If you don't know the answer to something, say you don't know. Don't make up facts.
* Along with technical discussion, include examples to explain in layman terms as well.
* Avoid using jargon unless necessary. If you use jargon, explain it.