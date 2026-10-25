# finode documentation

finode is a personal finance app built on double-entry bookkeeping, with envelope budgeting, a minimal web UI and an MCP server for AI assistants.

## Pick your path

| I want to… | Read |
|---|---|
| **use** finode (testers and the owner) | the [user guide](#user-guide) |
| **understand how it is built** | the [architecture](#architecture) |
| **change the code** | the [developer docs](#developer) |
| **set it up or deploy it** | the [README](../README.md) and [Data and operations](architecture/data-and-ops.md) |

## User guide

1. [Getting started](guide/getting-started.md): sign up, the first account, the first expense
2. [Accounts and categories](guide/accounts-and-categories.md)
3. [Transactions](guide/transactions.md): adding, splitting, upcoming, recently deleted
4. [Budgeting](guide/budgeting.md): Ready to assign, categories, cards, goals
5. [Recurring transactions, settings and your data](guide/recurring-and-settings.md)
6. [Using finode from an AI assistant](guide/mcp.md)

## Architecture

Read in this order:

1. [Overview](architecture/overview.md): layers, request flow, the pieces around the app
2. [The ledger](architecture/ledger.md): accounts, postings, balancing, history
3. [The budget](architecture/budget.md): the envelope arithmetic
4. [The web UI](architecture/web-ui.md): templates, htmx, how a page updates
5. [The design system](architecture/design.md): the look, the parts every page is made of, motion, the rules behind them
6. [MCP and authentication](architecture/mcp-and-auth.md): sign-in, tokens, OAuth, tools
7. [Data and operations](architecture/data-and-ops.md): schema, migrations, backup, Docker, deployment

## Developer

- [Code map](developer/code-map.md): where everything lives and where to start reading
- [Plan: tags apart from notes](developer/tags-plan.md): a proposal, not built
- [The JSON API](developer/api.md): every route, and what is left out on purpose
- [Conventions and how-tos](developer/conventions.md): the rules, adding a page, a tool, a migration, a setting
- [Why it is built this way](developer/decisions.md): the decisions that look odd until you know the reason

## About these docs

- Diagrams are [Mermaid](https://mermaid.js.org/); GitHub renders them.
- `CLAUDE.md` in the repository root is the dense rulebook for AI coding assistants. It covers the same ground as the developer docs in more detail; when behaviour changes, update both.
- When a doc and the code disagree, the code is right. Please fix the doc.
