# Contributing to cds-text-sync

First off, thank you for your interest in `cds-text-sync`! It's great to see the community engaging with modern workflows for CODESYS.

## 🛡️ Development Policy

To ensure the architectural integrity and long-term stability of this tool, **I am currently not accepting Pull Requests (PRs) involving core logic changes.** I prefer to review all feedback and implement improvements personally. This ensures that every line of code aligns with the project's vision and remains safe for industrial use.

---

## 🚀 How Can I Help?

### 1. Reporting Bugs

If you find a bug, please open an **[Issue](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=1-bug.yml)**. This is the most helpful thing you can do! The form asks for a few specifics up front:

- What version of CODESYS are you using? (exact build from `Help → About` — patch level matters)
- What language is the CODESYS UI set to? (localized IDEs write localized object paths)
- What was the error message or unexpected behavior?
- Can you provide a small code snippet to reproduce the issue?

### 2. Suggesting Enhancements

I am always looking for ways to improve the workflow. If you have an idea:

- Open a **[Feature request](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=2-feature.yml)**.
- Explain the use case and why it would be beneficial for your workflow.
- I will review these suggestions and prioritize them for future updates.

### 3. Telling Me What Feels Awkward

This is the feedback I receive least of and value most.

Bugs get reported because they hurt. Rough edges do not — people work around them silently, and I never learn the tool has one. If a step confuses you, if you keep forgetting which command runs in which direction, if a message leaves you unsure whether your project is in a safe state: open a **[Friction report](https://github.com/ArthurkaX/cds-text-sync/issues/new?template=3-friction.yml)**.

No reproduction steps, no version numbers, no proposed fix required. Half a sentence is a complete report. "I don't know what this option does" is genuinely useful — it means the documentation failed, and that is a defect too.

### 4. Weighing In on Direction

Roadmap decisions are posted as **[Polls](https://github.com/ArthurkaX/cds-text-sync/discussions/categories/polls)** and as issues labelled `roadmap`, where reactions count as votes. Both take one click.

If a click is not enough to express what you mean, **[Discussions](https://github.com/ArthurkaX/cds-text-sync/discussions)** are open for anything that does not belong in an issue: disagreement with a design decision, a use case the tool does not serve, an observation about how your team actually works. You do not need a proposal or evidence to start one — an objection backed only by experience is still worth reading.

### 5. Submitting Compatibility Examples

To keep this repository lightweight and minimalist, all test cases, problematic objects, and compatibility examples are hosted in a separate **[Reference Project](https://github.com/ArthurkaX/cds-text-sync-reference-project)**.

If you encounter an object that cannot be exported or imported correctly, please refer to that repository's README for detailed contribution guidelines and verification procedures.

## 🍴 Forking

If you need a specific feature immediately or want to experiment with the code, feel free to **Fork** the repository! That is the beauty of the MIT License. You are welcome to maintain your own version for your specific needs.

## ⚖️ License

By participating in discussions or reporting issues, you agree that any feedback provided may be used to improve the project under its **MIT License**.
