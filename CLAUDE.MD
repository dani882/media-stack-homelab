# Claude Handoff

Repository: `/Users/jesusrivera/home-labs/homelab`

Current branch: `feat/spanish-language-upgrades`

Before making any change, read the full canonical checkpoint:

`/Users/jesusrivera/home-labs/homelab/docs/HOMELAB_MEDIA_CONTEXT.md`

That file is the source of truth for:

- the Spanish-language upgrade policy
- the `/data` hardlink migration
- live NAS state
- private tracker constraints, including Milnueve seeding requirements
- completed validations
- known risks
- remaining work

Working rules:

- Do not assume the git worktree is clean.
- Do not reset, restore, stash, discard, or change branches.
- Do not remove `/downloads` or `/media` compatibility mounts yet.
- Do not disrupt private torrent seeding.
- Do not perform destructive NAS changes without showing the exact command first.
- Documentation and repo comments should stay in English.

Start every continuation with:

```bash
git branch --show-current
git status --short
git diff --check
git diff --stat
make check
```

Then continue from the state described in `docs/HOMELAB_MEDIA_CONTEXT.md`.
